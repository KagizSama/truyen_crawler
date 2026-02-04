from fastapi import APIRouter, HTTPException, Query
from app.services.search_service import SearchService
from typing import List, Optional
from pydantic import BaseModel
from loguru import logger

router = APIRouter()

class SearchResult(BaseModel):
    story_id: int
    chapter_id: int
    story_title: str
    chapter_title: str
    content: str
    url: str
    score: float

@router.get("/search", response_model=List[SearchResult])
async def search_stories(
    q: str = Query(..., description="Query to search for"),
    limit: int = Query(5, description="Number of results to return"),
    story_id: Optional[int] = Query(None, description="Optional filter by story ID")
):
    try:
        search_service = SearchService()
        hits = await search_service.hybrid_search(
            query=q,
            limit=limit,
            story_id=story_id
        )
        
        results = []
        for hit in hits:
            source = hit['_source']
            results.append(SearchResult(
                story_id=source.get('story_id'),
                chapter_id=source.get('chapter_id'),
                story_title=source.get('story_title'),
                chapter_title=source.get('chapter_title', "Chapter"),
                content=source.get('content'),
                url=source.get('url'),
                score=hit['_score']
            ))
            
        return results
            
    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'search_service' in locals():
            await search_service.close()
