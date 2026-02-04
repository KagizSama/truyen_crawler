from app.services.search_service import SearchService
from app.services.crawler import CrawlerService
from app.schemas.story import StoryData
import asyncio
from typing import List, Dict, Any
from loguru import logger

# Wrapper class to hold service instances if needed, 
# but for Gemini tools, simple functions are often easier.
# However, we need access to the async services.

async def search_library(query: str) -> Dict[str, Any]:
    """
    Search for novels, characters, or plot details in the library.
    
    Args:
        query: The search query (e.g., "truyện tiên hiệp hay", "nhân vật Ngu Dung Ca").
    
    Returns:
        JSON containing list of relevant story chunks.
    """
    service = SearchService()
    try:
        hits = await service.hybrid_search(query, limit=10)
        results = []
        for hit in hits:
            source = hit['_source']
            results.append({
                "story": source.get('story_title'),
                "chapter": source.get('chapter_title'),
                "content": source.get('content')
            })
        return {"results": results}
    except Exception as e:
        return {"error": str(e)}
    finally:
        await service.close()

async def crawl_story(url: str) -> Dict[str, str]:
    """
    Download/Crawl a new story from a URL (truyenfull.vn, etc.) into the library.
    Use this when the user explicitly asks to add or download a story.
    
    Args:
        url: The full URL of the story to crawl.
        
    Returns:
        Status message indicating the crawl has started.
    """
    crawler = CrawlerService()
    
    try:
        # Just fetch metadata to verify valid link
        metadata = await crawler.get_metadata(url)
        
        # Wait for the crawl to finish (Synchronous Tool Execution)
        # This ensures the UI remains in "Processing" state until done.
        # Note: If crawl is very long, this might timeout, but for typical use it's better UX as per request.
        story_data = await crawler.crawl_story(url)
        
        # Save to Database
        story_id = await crawler.save_story_to_db(story_data)
        
        # Auto-index to Elasticsearch
        try:
            search_service = SearchService()
            try:
                await search_service.vectorize_and_index_story(story_id)
                index_status = " và đã được lập chỉ mục để tìm kiếm"
            finally:
                await search_service.close()
        except Exception as e:
            logger.error(f"Auto-indexing failed for story {story_id}: {e}")
            index_status = " nhưng việc lập chỉ mục gặp lỗi"
        
        return {
            "status": "success",
            "message": f"Đã cào thành công truyện '{metadata.title}' vào thư viện{index_status}!",
            "story_title": metadata.title
        }
    except Exception as e:
        return {"error": f"Lỗi khi cào truyện: {str(e)}"}
