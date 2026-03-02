"""LangGraph-based AI agent with multi-step reasoning and persistent memory."""
from typing import TypedDict, Annotated, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from app.services.langgraph_tools import LANGGRAPH_TOOLS
from app.utils.redis_checkpointer import RedisCheckpointer
from app.core.config import settings
from loguru import logger
import operator
import asyncio
import time


# === Simple-query shortcut: skip LLM entirely for greetings/thanks ===
SIMPLE_RESPONSES = {
    "greetings": {
        "patterns": ["chào", "hello", "hi ", "xin chào", "hey", "ê ", "ê!"],
        "response": "Chào bạn! Mình là trợ lý tìm kiếm và tóm tắt truyện. Bạn cần mình hỗ trợ gì?"
    },
    "thanks": {
        "patterns": ["cảm ơn", "thanks", "thank you", "cám ơn", "tks", "ok cảm ơn"],
        "response": "Không có gì! Bạn cần mình hỗ trợ thêm gì không?"
    },
    "goodbye": {
        "patterns": ["tạm biệt", "bye", "goodbye", "bái bai"],
        "response": "Tạm biệt bạn! Hẹn gặp lại!"
    },
    "ok": {
        "patterns": ["ok", "oke", "okie", "được rồi", "ừ", "ờ"],
        "response": "Bạn cần mình tìm kiếm hoặc tóm tắt truyện gì thêm không?"
    }
}

MAX_HISTORY_MESSAGES = 10  # Chỉ giữ 10 messages gần nhất (~5 turns)


def _match_simple_query(query: str) -> Optional[str]:
    """Check if query matches a simple pattern, return response or None."""
    query_lower = query.lower().strip()
    # Only match short queries (< 30 chars) to avoid false positives
    if len(query_lower) > 30:
        return None
    for category in SIMPLE_RESPONSES.values():
        for pattern in category["patterns"]:
            if query_lower.startswith(pattern) or query_lower == pattern.strip():
                return category["response"]
    return None


# State definition
class AgentState(TypedDict):
    """State for the LangGraph agent."""
    messages: Annotated[List, operator.add]
    session_id: str
    plan: Optional[str]
    should_reflect: bool
    final_answer: Optional[str]
    retry_count: int
    critique: Optional[str]
    quota_exhausted: bool


class LangGraphAgent:
    """
    LangGraph-based agent with multi-step tool calling and persistent memory.
    
    Features:
    - Multi-step tool execution (no 1-call limit)
    - Planning before execution
    - Optional reflection for answer quality
    - Persistent memory via Redis
    """
    
    def __init__(self):
        self.checkpointer = RedisCheckpointer()
        self.llm = ChatGoogleGenerativeAI(
            model=settings.GEMINI_MODEL,
            google_api_key=settings.GEMINI_API_KEY,
            temperature=0.7
        )
        self.llm_with_tools = self.llm.bind_tools(LANGGRAPH_TOOLS)
        self.graph = self._build_graph()
        
    def _build_graph(self) -> StateGraph:
        """Build the agent StateGraph."""
        workflow = StateGraph(AgentState)
        
        # Add nodes
        workflow.add_node("agent", self._agent_node)
        workflow.add_node("tools", ToolNode(LANGGRAPH_TOOLS))
        
        if settings.ENABLE_REFLECTION:
            workflow.add_node("reflect", self._reflect_node)
        
        # Set entry point
        workflow.set_entry_point("agent")
        
        # Add conditional edges
        workflow.add_conditional_edges(
            "agent",
            self._should_continue,
            {
                "continue": "tools",
                "reflect": "reflect" if settings.ENABLE_REFLECTION else END,
                "end": END
            }
        )
        
        # Tools always go back to agent
        workflow.add_edge("tools", "agent")
        
        # Reflection logic
        if settings.ENABLE_REFLECTION:
            workflow.add_conditional_edges(
                "reflect",
                self._should_retry,
                {
                    "retry": "agent",
                    "end": END
                }
            )
        
        return workflow.compile()
    
    async def _agent_node(self, state: AgentState) -> AgentState:
        """
        Agent reasoning node.
        Decides whether to call tools or provide final answer.
        """
        messages = state["messages"]
        
        # Add system message if not present
        if not any(isinstance(m, SystemMessage) for m in messages):
            system_msg = SystemMessage(content=self._get_system_prompt())
            messages = [system_msg] + messages
            
        # If there is a critique, inject it as a user message to guide the agent
        critique = state.get("critique")
        if critique:
            logger.info(f"Injecting critique: {critique}")
            messages = messages + [
                HumanMessage(content=f"Lần trước bạn trả lời chưa tốt. Nhận xét: {critique}. Hãy trả lời lại tốt hơn và khắc phục các vấn đề trên.")
            ]
        
        # Invoke LLM with rate-limit error handling
        try:
            response = await self.llm_with_tools.ainvoke(messages)
        except Exception as e:
            if "ResourceExhausted" in str(e) or "429" in str(e):
                logger.warning(f"Quota exhausted in agent node: {e}")
                response = AIMessage(
                    content="Xin lỗi, hệ thống AI đang tạm thời quá tải (hết quota). "
                            "Vui lòng thử lại sau khoảng 1 phút."
                )
                return {
                    "messages": [response],
                    "session_id": state["session_id"],
                    "should_reflect": False,
                    "retry_count": state.get("retry_count", 0),
                    "critique": None,
                    "quota_exhausted": True
                }
            raise
        
        return {
            "messages": [response],
            "session_id": state["session_id"],
            "should_reflect": state.get("should_reflect", False),
            "retry_count": state.get("retry_count", 0),
            "critique": None, # Clear critique after using it
            "quota_exhausted": False
        }
    
    async def _reflect_node(self, state: AgentState) -> AgentState:
        """
        Reflection node to verify answer quality.
        """
        messages = state["messages"]
        
        # Get the last AI message
        last_ai_msg = None
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and not msg.tool_calls:
                last_ai_msg = msg
                break
        
        if not last_ai_msg:
            return state
        
        reflection_prompt = f"""Đánh giá chất lượng câu trả lời sau:

Câu trả lời: {last_ai_msg.content}

Checklist:
1. Có trả lời đúng câu hỏi không?
2. Có bịa đặt thông tin không có trong search results?
3. Có đủ chi tiết không?
4. Có cần thêm thông tin gì?

Nếu câu trả lời tốt, trả về "GOOD".
Nếu cần cải thiện, hãy bắt đầu bằng "BAD:" và giải thích lý do ngắn gọn."""

        reflection = await self.llm.ainvoke([HumanMessage(content=reflection_prompt)])
        result = reflection.content.strip()
        
        logger.info(f"Reflection result: {result}")
        
        if result.startswith("BAD") or "cần cải thiện" in result.lower():
            # Extract critique
            critique = result.replace("BAD:", "").strip()
            return {
                "messages": [], # No new messages from here
                "session_id": state["session_id"],
                "retry_count": state.get("retry_count", 0) + 1,
                "critique": critique,
                "should_reflect": True # Keep reflection enabled
            }
        
        return {
            "messages": [],
            "session_id": state["session_id"],
            "retry_count": state.get("retry_count", 0),
            "critique": None,
            "should_reflect": True
        }
    
    def _should_continue(self, state: AgentState) -> str:
        """Decide whether to continue to tools, reflect, or end."""
        # Skip reflection entirely when quota is exhausted
        if state.get("quota_exhausted"):
            logger.info("Quota exhausted — skipping reflection, going to END")
            return "end"
        
        messages = state["messages"]
        last_message = messages[-1]
        
        # If LLM wants to call tools
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "continue"
        
        # Smart reflection: CHỈ reflect khi agent đã thực sự dùng tool
        # Nếu agent trả lời trực tiếp (chào hỏi, câu đơn giản) → skip reflection
        if settings.ENABLE_REFLECTION:
            has_tool_usage = any(isinstance(m, ToolMessage) for m in messages)
            if has_tool_usage:
                return "reflect"
            else:
                logger.debug("Skipping reflection — no tool usage detected")
        
        return "end"

    async def _should_retry(self, state: AgentState) -> str:
        """Decide whether to retry based on reflection."""
        critique = state.get("critique")
        retry_count = state.get("retry_count", 0)
        MAX_RETRIES = 2
        
        if critique and retry_count < MAX_RETRIES:
            logger.info(f"Retrying agent (attempt {retry_count + 1}/{MAX_RETRIES}), waiting 15s for quota refresh...")
            await asyncio.sleep(15)  # Wait for Gemini free tier quota to refresh
            return "retry"
        
        if critique:
            logger.warning("Max retries reached, giving up.")
            
        return "end"
            
    def _get_system_prompt(self) -> str:
        """Get system prompt for the agent."""
        return """Bạn là trợ lý thông minh chuyên về tiểu thuyết Trung Quốc và Việt Nam.

CÔNG CỤ CÓ SẴN:
- search_library: Tìm kiếm NỘI DUNG truyện (nhân vật, cốt truyện, sự kiện) trong thư viện
- browse_library: Duyệt thư viện — liệt kê thể loại, xem truyện theo thể loại, gợi ý truyện, tra cứu thông tin truyện
- crawl_story: Tải truyện mới vào thư viện từ URL

KHI NÀO DÙNG TOOL NÀO:
1. User hỏi "có thể loại gì?" → browse_library(action='list_genres')
2. User hỏi "truyện tiên hiệp" hoặc "truyện [thể loại]" → browse_library(action='list_stories', genre='Tiên Hiệp')
3. User hỏi "recommend/giới thiệu/có gì hay" → browse_library(action='random_recommend')
4. User hỏi "giới thiệu truyện [thể loại]" → browse_library(action='random_recommend', genre='...')
5. User hỏi thông tin truyện (tác giả, số chương, URL, trạng thái) → browse_library(action='get_story_info', title='tên truyện')
6. User hỏi về nội dung/nhân vật/cốt truyện → search_library(query='...')
7. User muốn tóm tắt truyện → search_library(query='tên truyện')
8. User cung cấp URL để tải truyện → crawl_story(url='...')

QUY TẮC QUAN TRỌNG:
1. LUÔN THỬ GỌI TOOL TRƯỚC — TUYỆT ĐỐI KHÔNG nói "tôi không có khả năng" mà không thử tool
2. Bạn có thể gọi tools NHIỀU LẦN nếu cần thiết
3. Khi nhận kết quả search_library:
   - ĐỌC CẨN THẬN TẤT CẢ các đoạn content
   - TỔNG HỢP thông tin từ NHIỀU chunks
   - TRÍCH DẪN tên nhân vật, sự kiện cụ thể
4. Khi nhận kết quả browse_library:
   - Trình bày danh sách truyện đẹp mắt (tên, tác giả, thể loại, trạng thái)
   - Thêm mô tả ngắn nếu có
   - Gợi ý user có thể hỏi thêm về nội dung bằng search_library
5. TUYỆT ĐỐI KHÔNG bịa đặt thông tin không có trong results
6. Nếu search trả về ít kết quả → nói rõ và đề xuất giải pháp

HƯỚNG DẪN TÓM TẮT:
- "tóm tắt bộ [tên]": search_library → tổng hợp từ nhiều chapters
- "tóm tắt tập 1": search_library với "tập 1" → chỉ tóm tắt chapters đầu
- Hỏi về nhân vật/sự kiện: search_library với tên cụ thể

ĐỊNH DẠNG TRẢ LỜI:
- Sử dụng ngôn ngữ tự nhiên, mạch lạc
- Chia đoạn rõ ràng cho dễ đọc
- Khi liệt kê truyện: dùng format rõ ràng với tiêu đề, tác giả, thể loại

LƯU Ý:
- Nếu user follow-up mà không nêu tên truyện → sử dụng context từ lịch sử chat
- Nếu search trả về quá ít kết quả → thông báo và suggest crawl thêm data
- BẠN CÓ THỂ GỌI NHIỀU TOOLS — đừng ngại sử dụng chúng khi cần!"""
    
    async def chat(
        self, 
        query: str, 
        session_id: str = "default"
    ) -> Dict[str, Any]:
        """
        Process a chat query with persistent state.
        
        Args:
            query: User query
            session_id: Session identifier for memory
            
        Returns:
            Dict containing answer, sources (if any), and metadata
        """
        # === Simple-query shortcut: 0 LLM calls ===
        simple_response = _match_simple_query(query)
        if simple_response:
            logger.info(f"Simple query shortcut: '{query}' → skipping LLM")
            return {
                "answer": simple_response,
                "sources": [],
                "session_id": session_id
            }
        
        # Connect to Redis if not connected
        if not self.checkpointer.redis and not self.checkpointer._fallback_memory:
            await self.checkpointer.connect()
        
        # Load previous state
        previous_state = await self.checkpointer.get(session_id) or {}
        
        # === History trimming: cap at MAX_HISTORY_MESSAGES ===
        previous_messages = previous_state.get("messages", [])
        if len(previous_messages) > MAX_HISTORY_MESSAGES:
            logger.info(f"Trimming history: {len(previous_messages)} → {MAX_HISTORY_MESSAGES} messages")
            previous_messages = previous_messages[-MAX_HISTORY_MESSAGES:]
        
        # === Sanitize history: remove tool call/response to avoid Gemini ordering errors ===
        # Gemini requires: function call must come after user turn or function response turn.
        # Old tool messages from previous conversations violate this rule.
        sanitized_messages = []
        for msg in previous_messages:
            if isinstance(msg, ToolMessage):
                # Skip tool response messages from old conversations
                continue
            if isinstance(msg, AIMessage) and msg.tool_calls:
                # Skip AI messages that contain tool calls (orphaned without ToolMessage)
                continue
            sanitized_messages.append(msg)
        
        if len(sanitized_messages) != len(previous_messages):
            logger.info(f"Sanitized history: {len(previous_messages)} → {len(sanitized_messages)} messages (removed tool call/response pairs)")
        
        previous_messages = sanitized_messages
        
        # Build initial state
        initial_state: AgentState = {
            "messages": previous_messages + [
                HumanMessage(content=query)
            ],
            "session_id": session_id,
            "plan": None,
            "should_reflect": False,
            "final_answer": None,
            "quota_exhausted": False
        }
        
        try:
            # Run the graph
            final_state = await self.graph.ainvoke(initial_state, config={"recursion_limit": settings.MAX_RECURSION_LIMIT})
        except Exception as e:
            # Check for quota exhaustion (string matching as fallback if class not imported)
            if "ResourceExhausted" in str(e) or "429" in str(e):
                logger.error(f"Quota exceeded: {e}")
                return {
                    "answer": "Rất xin lỗi, hiện tại hệ thống AI đang bị quá tải (hết quota Google). Vui lòng thử lại sau giây lát hoặc liên hệ quản trị viên.",
                    "sources": [],
                    "session_id": session_id
                }
            if "Invalid argument" in str(e) or "function call turn" in str(e):
                logger.error(f"Gemini message ordering error: {e}")
                # Clear corrupted session state so next request works
                await self.checkpointer.put(session_id, {"messages": []})
                return {
                    "answer": "Xin lỗi, đã xảy ra lỗi kỹ thuật với lịch sử chat. Mình đã reset phiên — bạn vui lòng hỏi lại nhé!",
                    "sources": [],
                    "session_id": session_id
                }
            logger.error(f"Graph execution failed: {e}")
            raise e
        
        # Debug: Log message types
        logger.debug(f"Final state has {len(final_state['messages'])} messages")
        for i, msg in enumerate(final_state['messages']):
            msg_type = type(msg).__name__
            logger.debug(f"  Message {i}: {msg_type}")
        
        # Save state
        await self.checkpointer.put(session_id, {
            "messages": final_state["messages"]
        })
        
        # Extract answer
        answer = ""
        sources = []
        
        # Find the last AI message without tool calls
        for msg in reversed(final_state["messages"]):
            if isinstance(msg, AIMessage):
                if not msg.tool_calls:
                    answer = msg.content
                    logger.debug(f"Found answer from AI message: {answer[:100]}...")
                    break
        
        # Fallback: if empty, try any AI message
        if not answer:
            logger.warning("No answer in standard extraction, trying fallback")
            for msg in reversed(final_state["messages"]):
                if isinstance(msg, AIMessage) and msg.content:
                    answer = msg.content
                    logger.warning(f"Using fallback answer: {answer[:100]}...")
                    break
        
        # Last resort fallback
        if not answer:
            logger.error("Failed to extract answer from agent")
            answer = "Chào bạn, bạn cần mình hỗ trợ tìm kiếm hoặc tóm tắt truyện gì?"
        
        # Extract sources from tool messages
        for msg in final_state["messages"]:
            if isinstance(msg, ToolMessage):
                # Parse tool result for sources
                # This is a simplified version
                pass
        
        return {
            "answer": answer,
            "sources": sources,
            "session_id": session_id
        }
    
    async def close(self):
        """Cleanup resources."""
        await self.checkpointer.close()
