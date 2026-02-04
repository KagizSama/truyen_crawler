import asyncio
import sys
import argparse
from sqlalchemy import select, update
from sqlalchemy.orm import joinedload
from app.db.session import AsyncSessionLocal
from app.db.models import Story, Chapter, ChapterChunk
from app.services.search_service import SearchService
from app.core.config import settings
from loguru import logger

async def reset_search(search_service: SearchService):
    logger.info("RESETTING search data...")
    async with AsyncSessionLocal() as session:
        try:
            logger.info("Clearing embeddings in Database...")
            await session.execute(update(ChapterChunk).values(embedding=None))
            await session.commit()
            logger.info("Database embeddings cleared.")
        except Exception as e:
            logger.error(f"Failed to clear DB embeddings: {e}")

    try:
        logger.info(f"Deleting Elasticsearch index: {search_service.index_name}")
        if await search_service.es.indices.exists(index=search_service.index_name):
            await search_service.es.indices.delete(index=search_service.index_name)
            logger.info("ES index deleted.")
    except Exception as e:
        logger.error(f"Failed to delete ES index: {e}")

async def backfill(reset: bool = False):
    search_service = SearchService()
    
    if reset:
        await reset_search(search_service)
    
    logger.info("Starting backfill process...")
    
    # 1. Get all stories
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(Story))
        stories = res.scalars().all()
        logger.info(f"Found {len(stories)} stories to process.")
        
        for story in stories:
            logger.info(f"Processing story: {story.title} (ID: {story.id})")
            try:
                # vectorize_and_index_story handles chunks that don't have embeddings
                # and indexes them into ES
                await search_service.vectorize_and_index_story(story.id)
            except Exception as e:
                logger.error(f"Failed to process story {story.id}: {e}")
                
    await search_service.close()
    logger.info("Backfill COMPLETED.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Unified search backfill script")
    parser.add_argument("--reset", action="store_true", help="Reset all embeddings and ES index before starting")
    args = parser.parse_args()
    
    asyncio.run(backfill(reset=args.reset))
