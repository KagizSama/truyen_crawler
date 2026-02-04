from pydantic import BaseModel
from typing import List, Optional

class Chapter(BaseModel):
    title: str
    url: str
    content: Optional[str] = None
    order: int

class StoryMetadata(BaseModel):
    title: str
    author: str
    genres: List[str]
    description: str
    status: str
    url: str

class StoryData(BaseModel):
    metadata: StoryMetadata
    chapters: List[Chapter]
    total_chapters: int

class CrawlRequest(BaseModel):
    url: str

class BatchCrawlRequest(BaseModel):
    list_url: str
    limit: Optional[int] = 10
