from google import genai
from app.core.config import settings
from app.schemas.agent import SourceNode, ChatResponse
from app.services.tools import search_library, crawl_story
from google.genai import types
from loguru import logger
import time
import json
from typing import List, Dict, Any

# Simple in-memory history cache: {session_id: [{"role": "user", "parts": "..."}, ...]}
active_sessions: Dict[str, List[dict]] = {}

class AgentService:
    def __init__(self):
        self._setup_gemini()
        
    def _setup_gemini(self):
        if not settings.GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY not set. Agent will not function.")
            return
            
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self.model_name = settings.GEMINI_MODEL
        key_masked = settings.GEMINI_API_KEY[:5] + "..." + settings.GEMINI_API_KEY[-5:] if settings.GEMINI_API_KEY else "None"
        logger.info(f"Configured Gemini with Key: {key_masked} | Model: {self.model_name}")
        
        # Define Tools
        self.tools = [search_library, crawl_story]
        self.tool_declarations = self._build_tool_declarations()
        
    def _get_history(self, session_id: str) -> List[dict]:
        if session_id not in active_sessions:
            active_sessions[session_id] = []
        return active_sessions[session_id]

    def _update_history(self, session_id: str, role: str, content: str):
        history = self._get_history(session_id)
        # Keep history reasonable size (e.g., last 20 messages)
        if len(history) > 20:
            history.pop(0)
        history.append({"role": "user" if role == "user" else "model", "parts": [content]})


    def _build_tool_declarations(self) -> List[types.Tool]:
        """
        Build tool declarations from Python functions for Gemini API.
        """
        declarations = []
        for func in self.tools:
            # Extract function signature
            func_name = func.__name__
            func_doc = func.__doc__ or f"Tool: {func_name}"
            
            # Build parameter schema based on function
            if func_name == "search_library":
                params = {
                    "type": "OBJECT",
                    "properties": {
                        "query": {
                            "type": "STRING",
                            "description": "Từ khóa tìm kiếm truyện, nhân vật, hoặc nội dung"
                        }
                    },
                    "required": ["query"]
                }
            elif func_name == "crawl_story":
                params = {
                    "type": "OBJECT",
                    "properties": {
                        "url": {
                            "type": "STRING",
                            "description": "URL của truyện cần tải"
                        }
                    },
                    "required": ["url"]
                }
            else:
                params = {"type": "OBJECT", "properties": {}}
            
            declarations.append(types.FunctionDeclaration(
                name=func_name,
                description=func_doc.strip(),
                parameters=params
            ))
        
        return [types.Tool(function_declarations=declarations)]
    
    async def _rewrite_query(self, query: str, history: List[dict]) -> str:
        """
        Rewrite the query to be self-contained based on history.
        """
        if not history:
            return query
            
        recent_history = history[-4:] # Last 2 turns
        history_text = "\n".join([f"{msg['role']}: {msg['parts'][0]}" for msg in recent_history])
        
        prompt = f"""Bạn là một chuyên gia ngôn ngữ. 
Nhiệm vụ: Viết lại câu hỏi sau đây sao cho nó đầy đủ ý nghĩa, thay thế các đại từ (nó, hắn, cô ấy, nhân vật này...) bằng tên riêng hoặc danh từ xác định dựa trên lịch sử hội thoại.
(QUAN TRỌNG: Giữ nguyên các danh từ riêng, tên truyện, tên nhân vật trong ngoặc kép hoặc viết hoa nếu có. Không được tự ý thay đổi từ khóa tìm kiếm quan trọng).

Lịch sử:
{history_text}

Câu hỏi gốc: "{query}"

Câu hỏi viết lại (chỉ trả về câu hỏi, không giải thích gì thêm):"""

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            rewritten = response.text.strip()
            logger.info(f"Original: '{query}' -> Rewritten: '{rewritten}'")
            return rewritten
        except Exception as e:
            logger.error(f"Query rewriting failed: {e}")
            return query

    async def chat(self, query: str, session_id: str = "default", story_id: int = None) -> ChatResponse:
        start_time = time.time()
        
        # 1. Update History
        history = self._get_history(session_id)
        
        # 2. Rewrite Query (Contextualization)
        # We still keep this helper as it improves tool accuracy (resolving args)
        rewritten_query = await self._rewrite_query(query, history)
        
        # 3. Chat Loop with Function Calling
        
        system_instruction = """Bạn là "Thủ Thư" (Librarian) - Hỗ trợ tìm kiếm và quản lý thư viện tiểu thuyết.
Phong cách: Thân thiện, cổ trang nhẹ nhàng.

CÔNG CỤ CÓ SẴN:
- `search_library(query)`: Dùng khi người dùng hỏi về nội dung, nhân vật, cốt truyện, hoặc tìm truyện.
- `crawl_story(url)`: Dùng khi người dùng đưa link và bảo "tải truyện", "cào truyện", "thêm truyện".

QUY TẮC TUYỆT ĐỐI (STRICT RULES):
1. Nếu người dùng chào hỏi xã giao -> Trả lời tự nhiên.
2. Nếu cần thông tin -> GỌI TOOL `search_library`.
3. Nếu kết quả tool trả về là RỖNG (`[]` hoặc không có kết quả):
   - TRẢ LỜI: "Xin lỗi, thư viện hiện tại chưa có bộ truyện [Tên Truyện] này."
   - SAU ĐÓ GỢI Ý: "Nếu ngài có link truyện từ truyenfull.vn hoặc các trang khác, tại hạ có thể giúp cào truyện về thư viện cho ngài."
4. Nếu người dùng nói "cào", "tải", "thêm", "download" mà KHÔNG có URL:
   - HỎI LẠI: "Xin ngài vui lòng cung cấp link truyện (ví dụ: https://truyenfull.vn/ten-truyen/) để tại hạ có thể tải về thư viện."
5. TUYỆT ĐỐI KHÔNG SỬ DỤNG kiến thức bên ngoài (training data) để bịa ra nội dung truyện nếu không có trong kết quả tìm kiếm.
6. Nếu người dùng đưa link -> GỌI TOOL `crawl_story`.
7. PHÂN BIỆT RÕ: Khi người dùng hỏi "Có truyện X không?":
   - Hãy kiểm tra kỹ trường `story` trong kết quả trả về.
   - Nếu KHÔNG thấy truyện nào có tên là X (hoặc gần giống X) -> BẮT BUỘC trả lời: "Xin lỗi, thư viện hiện tại chưa có bộ truyện [Tên Truyện] này."
   - TUYỆT ĐỐI KHÔNG lôi các truyện khác (truyện Y, Z) ra để trả lời chỉ vì chúng có chứa từ khóa của X. Người dùng sẽ cảm thấy bị lừa.
   - Chỉ trả lời "Có" nếu tìm thấy đúng truyện.
"""
        
        # Build messages for Gemini
        messages = []
        messages.append({"role": "user", "parts": [system_instruction]})
        messages.append({"role": "model", "parts": ["Tại hạ đã rõ. Xin mời độc giả ra lệnh."]})
        messages.extend(history)
        messages.append({"role": "user", "parts": [rewritten_query]})
        
        sources = []
        final_answer = ""
        tool_name = None  # Track which tool was called
        
        try:
            # Convert messages to new format
            contents = []
            for msg in messages:
                role = msg.get("role")
                parts_data = msg.get("parts", [])
                
                if role in ["user", "model"]:
                    if isinstance(parts_data, list) and len(parts_data) > 0:
                        contents.append(types.Content(
                            role=role,
                            parts=[types.Part.from_text(parts_data[0])]
                        ))
            
            # First turn: Gemini decides to call tool or answer
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    tools=self.tool_declarations,
                    system_instruction=system_instruction
                )
            )
            
            # Check for function call in the first candidate's first part
            # Safe access pattern
            if not response.candidates or not response.candidates[0].content.parts:
                final_answer = "Xin lỗi, không nhận được phản hồi từ Gemini."
            else:
                part = response.candidates[0].content.parts[0]
                
                # Check for function call
                if part.function_call:
                    fc = part.function_call
                    fn_name = fc.name
                    # Convert MapComposite to dict safely
                    fn_args = {k: v for k, v in fc.args.items()}
                    
                    logger.info(f"Gemini requested tool: {fn_name} with args: {fn_args}")
                    tool_name = fn_name  # Track for frontend status
                
                    # Execute Tool
                    tool_result = {}
                    if fn_name == "search_library":
                        # Explicitly extract the query argument. Sometimes Gemini calls it 'query', sometimes something else if not strict.
                        # But Python kwargs matching usually works if schema is inferred correctly.
                        q = fn_args.get("query")
                        if q:
                            tool_result = await search_library(q)
                            # Extract sources for UI
                            if tool_result.get("results"):
                                for res in tool_result["results"]:
                                    sources.append(SourceNode(
                                        story_title=res.get("story", "Unknown"),
                                        chapter_title=res.get("chapter", "Unknown"),
                                        content_snippet=res.get("content", "")[:100] + "...",
                                        score=0.0
                                    ))
                        else:
                             tool_result = {"error": "Missing query argument"}

                    elif fn_name == "crawl_story":
                        url = fn_args.get("url")
                        if url:
                             tool_result = await crawl_story(url)
                        else:
                             tool_result = {"error": "Missing url argument"}
                    
                    # Send Tool Result back to Gemini with new API
                    # Build contents list with user query, function call, and function response
                    
                    # Add function call content
                    contents.append(response.candidates[0].content)
                    
                    # Add function response
                    function_response_part = types.Part.from_function_response(
                        name=fn_name,
                        response={"result": tool_result}
                    )
                    contents.append(types.Content(
                        role="tool",
                        parts=[function_response_part]
                    ))
                    
                    # Second turn: Gemini generates answer based on tool result
                    response2 = self.client.models.generate_content(
                        model=self.model_name,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            tools=self.tool_declarations,
                            system_instruction=system_instruction
                        )
                    )
                    
                    if not response2.candidates or not response2.candidates[0].content.parts:
                         final_answer = "Xin lỗi, không nhận được phản hồi từ hệ thống."
                    else:
                        part2 = response2.candidates[0].content.parts[0]
                        if part2.function_call:
                            # If it tries to call another function, we stop here for now (single-turn limit)
                            # Or we could just tell the user specific info is missing.
                            logger.warning(f"Gemini attempted recursive tool call: {part2.function_call.name}")
                            final_answer = "Xin lỗi, tôi cần thêm bước xử lý nhưng hệ thống giới hạn 1 lượt gọi công cụ."
                        else:
                            final_answer = part2.text
                    
                    # Update history with the user query and the FINAL answer only (simplification for UI history)
                    
                else:
                    # No tool call, just simple chat or text response
                    final_answer = part.text

        except Exception as e:
            logger.error(f"Gemini interaction failed: {e}")
            final_answer = "Xin lỗi, hệ thống đang gặp lỗi kỹ thuật."
            
        # Update history (User -> Model)
        self._update_history(session_id, "user", query)
        self._update_history(session_id, "model", final_answer)
        
        latency = time.time() - start_time
        
        # Filter sources: Only return if user explicitly asks for them or implies checking sources
        # Keywords: nguồn, link, đâu, source, chapter, chương, tập
        show_sources_keywords = ["nguồn", "link", "đâu", "source", "chapter", "chương", "tập", "trích dẫn"]
        should_show_sources = any(k in query.lower() for k in show_sources_keywords)
        
        return ChatResponse(
            answer=final_answer,
            sources=sources if should_show_sources else [], 
            latency=latency,
            tool_name=tool_name
        )
