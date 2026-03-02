"""LangChain-compatible tools for the AI agent."""
from typing import Dict, Any, Optional, List
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from app.services.search_service import SearchService
from app.services.crawler import CrawlerService
from app.db.session import AsyncSessionLocal
from app.db.models import Story, Chapter
from sqlalchemy import select, func
from loguru import logger
import random


# Input Schemas
class SearchLibraryInput(BaseModel):
    """Input schema for search_library tool."""
    query: str = Field(
        description="Từ khóa tìm kiếm truyện trong thư viện. Có thể là tên truyện, nhân vật, cốt truyện, hoặc sự kiện."
    )


class CrawlStoryInput(BaseModel):
    """Input schema for crawl_story tool."""
    url: str = Field(
        description="URL đầy đủ của truyện cần tải (ví dụ: https://truyenfull.vn/...)"
    )


@tool("search_library", args_schema=SearchLibraryInput, return_direct=False)
async def search_library_tool(query: str) -> Dict[str, Any]:
    """
    Tìm kiếm nội dung truyện trong thư viện bằng hybrid search (text + vector).
    
    Sử dụng khi:
    - User hỏi về nội dung, nhân vật, cốt truyện của một bộ truyện
    - User muốn tóm tắt truyện
    - User hỏi về sự kiện cụ thể trong truyện
    
    Args:
        query: Từ khóa tìm kiếm
        
    Returns:
        Dictionary chứa kết quả search với format:
        {
            "results": [{"story": str, "chapter": str, "content": str, "score": float}],
            "metadata": {"query_type": str, "total_results": int}
        }
    """
    service = SearchService()
    try:
        # Intent classification
        query_lower = query.lower()
        
        is_summary = any(keyword in query_lower for keyword in [
            "tóm tắt", "tóm lược", "kể", "nội dung", "cốt truyện", "câu chuyện"
        ])
        
        is_volume_specific = any(keyword in query_lower for keyword in [
            "tập 1", "tập 2", "tập đầu", "tập cuối",
            "chương 1", "chương đầu", "phần đầu", "phần 1"
        ])
        
        # Adjust retrieval depth
        limit = 50 if is_summary else 30
            
        # Perform hybrid search
        hits = await service.hybrid_search(query, limit=limit)
        
        # Process results
        results = []
        seen_chapters = set()
        
        for hit in hits:
            source = hit['_source']
            chapter_key = f"{source.get('story_title')}_{source.get('chapter_title')}"
            
            # For summaries, deduplicate by chapter
            if is_summary and chapter_key in seen_chapters:
                continue
                
            results.append({
                "story": source.get('story_title'),
                "chapter": source.get('chapter_title'),
                "content": source.get('content'),
                "score": hit.get('_score', 0)
            })
            
            if is_summary:
                seen_chapters.add(chapter_key)
        
        metadata = {
            "query_type": "summary" if is_summary else "search",
            "is_volume_specific": is_volume_specific,
            "total_results": len(results)
        }
        
        return {
            "results": results,
            "metadata": metadata
        }
    except Exception as e:
        logger.error(f"Search library failed: {e}")
        return {"error": str(e), "results": [], "metadata": {}}
    finally:
        await service.close()


@tool("crawl_story", args_schema=CrawlStoryInput, return_direct=False)
async def crawl_story_tool(url: str) -> Dict[str, str]:
    """
    Tải một truyện mới vào thư viện từ URL (truyenfull.vn, etc).
    
    Sử dụng khi:
    - User yêu cầu thêm/tải một truyện mới
    - Search không tìm thấy truyện và user cung cấp URL
    
    Args:
        url: URL đầy đủ của truyện
        
    Returns:
        Dictionary chứa status message:
        {
            "status": "success" | "error",
            "message": str,
            "story_title": str (nếu success)
        }
    """
    crawler = CrawlerService()
    
    try:
        # Verify URL and get metadata
        metadata = await crawler.get_metadata(url)
        
        # Crawl story
        story_data = await crawler.crawl_story(url)
        
        # Save to database
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
        logger.error(f"Crawl story failed: {e}")
        return {
            "status": "error",
            "error": f"Lỗi khi cào truyện: {str(e)}"
        }


# === Browse Library Tool: query PostgreSQL metadata ===

class BrowseLibraryInput(BaseModel):
    """Input schema for browse_library tool."""
    action: str = Field(
        description="Hành động cần thực hiện: 'list_genres' (liệt kê thể loại), "
                    "'list_stories' (liệt kê truyện theo thể loại), "
                    "'random_recommend' (gợi ý truyện ngẫu nhiên), "
                    "'get_story_info' (xem thông tin chi tiết một truyện)"
    )
    genre: Optional[str] = Field(
        default=None,
        description="Thể loại để lọc (ví dụ: 'Tiên Hiệp', 'Ngôn Tình'). "
                    "Chỉ cần thiết cho action 'list_stories' và 'random_recommend'."
    )
    title: Optional[str] = Field(
        default=None,
        description="Tên truyện cần tra cứu thông tin. "
                    "Chỉ cần thiết cho action 'get_story_info'."
    )


@tool("browse_library", args_schema=BrowseLibraryInput, return_direct=False)
async def browse_library_tool(action: str, genre: Optional[str] = None, title: Optional[str] = None) -> Dict[str, Any]:
    """
    Duyệt thư viện truyện: liệt kê thể loại, xem truyện theo thể loại, gợi ý ngẫu nhiên, hoặc tra cứu thông tin chi tiết.
    
    KHÔNG tìm kiếm nội dung bên trong truyện — dùng search_library cho việc đó.
    
    Sử dụng khi:
    - User hỏi "có thể loại gì?" → action='list_genres'
    - User hỏi "truyện tiên hiệp nào?" → action='list_stories', genre='Tiên Hiệp'
    - User hỏi "recommend/giới thiệu truyện" → action='random_recommend'
    - User hỏi "có bộ nào hay?" → action='random_recommend'
    - User hỏi "tác giả truyện X", "số chương truyện X", "URL truyện X" → action='get_story_info', title='X'
    
    Args:
        action: 'list_genres' | 'list_stories' | 'random_recommend' | 'get_story_info'
        genre: Tên thể loại (optional, cho list_stories và random_recommend)
        title: Tên truyện (optional, cho get_story_info)
    
    Returns:
        Dictionary chứa kết quả tương ứng với action
    """
    try:
        async with AsyncSessionLocal() as session:
            if action == "list_genres":
                # List all unique genres with story count
                result = await session.execute(
                    select(
                        func.unnest(Story.genres).label("genre"),
                        func.count().label("count")
                    ).group_by("genre").order_by(func.count().desc())
                )
                genres = [{"genre": row.genre, "story_count": row.count} for row in result.all()]
                return {
                    "action": "list_genres",
                    "genres": genres,
                    "total_genres": len(genres)
                }
            
            elif action == "list_stories":
                # List stories, optionally filtered by genre
                query = select(
                    Story.title, Story.author, Story.genres, 
                    Story.status, Story.description
                )
                if genre:
                    query = query.where(Story.genres.any(genre))
                query = query.order_by(Story.title).limit(20)
                
                result = await session.execute(query)
                stories = []
                for row in result.all():
                    stories.append({
                        "title": row.title,
                        "author": row.author,
                        "genres": row.genres,
                        "status": row.status,
                        "description": (row.description[:200] + "...") if row.description and len(row.description) > 200 else row.description
                    })
                return {
                    "action": "list_stories",
                    "filter_genre": genre,
                    "stories": stories,
                    "total": len(stories)
                }
            
            elif action == "random_recommend":
                # Random recommend 5 stories, optionally filtered by genre
                query = select(
                    Story.title, Story.author, Story.genres,
                    Story.status, Story.description
                )
                if genre:
                    query = query.where(Story.genres.any(genre))
                
                result = await session.execute(query)
                all_stories = result.all()
                
                # Pick random 5 (or less if not enough)
                sample_size = min(5, len(all_stories))
                picked = random.sample(all_stories, sample_size) if all_stories else []
                
                stories = []
                for row in picked:
                    stories.append({
                        "title": row.title,
                        "author": row.author,
                        "genres": row.genres,
                        "status": row.status,
                        "description": (row.description[:200] + "...") if row.description and len(row.description) > 200 else row.description
                    })
                return {
                    "action": "random_recommend",
                    "filter_genre": genre,
                    "stories": stories,
                    "total_available": len(all_stories),
                    "recommended": len(stories)
                }
            
            elif action == "get_story_info":
                # Get detailed info for a specific story by title
                if not title:
                    return {"error": "Cần cung cấp 'title' cho action 'get_story_info'."}
                
                # Subquery to count chapters per story
                chapter_count_subq = (
                    select(
                        Chapter.story_id,
                        func.count(Chapter.id).label("chapter_count")
                    )
                    .group_by(Chapter.story_id)
                    .subquery()
                )
                
                # Main query: fuzzy match title + join chapter count
                query = (
                    select(
                        Story.title, Story.author, Story.genres,
                        Story.status, Story.url, Story.description,
                        Story.created_at,
                        func.coalesce(chapter_count_subq.c.chapter_count, 0).label("chapter_count")
                    )
                    .outerjoin(chapter_count_subq, Story.id == chapter_count_subq.c.story_id)
                    .where(Story.title.ilike(f"%{title}%"))
                    .order_by(Story.title)
                    .limit(10)
                )
                
                result = await session.execute(query)
                stories = []
                for row in result.all():
                    stories.append({
                        "title": row.title,
                        "author": row.author,
                        "genres": row.genres,
                        "status": row.status,
                        "url": row.url,
                        "description": row.description,
                        "chapter_count": row.chapter_count,
                        "created_at": row.created_at.isoformat() if row.created_at else None
                    })
                
                if not stories:
                    return {
                        "action": "get_story_info",
                        "query_title": title,
                        "stories": [],
                        "message": f"Không tìm thấy truyện nào có tên '{title}' trong thư viện. "
                                   f"Bạn có thể thử search_library hoặc crawl_story để thêm truyện mới."
                    }
                
                return {
                    "action": "get_story_info",
                    "query_title": title,
                    "stories": stories,
                    "total": len(stories)
                }
            
            else:
                return {"error": f"Unknown action: {action}. Use 'list_genres', 'list_stories', 'random_recommend', or 'get_story_info'."}
                
    except Exception as e:
        logger.error(f"Browse library failed: {e}")
        return {"error": str(e)}


# Export tools as list for LangGraph
LANGGRAPH_TOOLS = [search_library_tool, browse_library_tool, crawl_story_tool]
