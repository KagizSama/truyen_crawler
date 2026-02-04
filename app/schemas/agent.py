from pydantic import BaseModel
from typing import List, Optional

class ChatRequest(BaseModel):
    query: str
    session_id: str = "default"
    story_id: Optional[int] = None
    history: Optional[List[dict]] = None

class SourceNode(BaseModel):
    story_title: str
    chapter_title: str
    content_snippet: str
    score: float

class ChatResponse(BaseModel):
    answer: str
    sources: List[SourceNode]
    latency: float
    tool_name: Optional[str] = None  # Track which tool was called (e.g., "crawl_story", "search_library")

