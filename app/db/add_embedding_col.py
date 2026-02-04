import asyncio
from sqlalchemy import text
from app.db.session import AsyncSessionLocal
from loguru import logger

async def add_column():
    async with AsyncSessionLocal() as session:
        try:
            logger.info("Attempting to add 'embedding' column to 'chapter_chunks' table...")
            # We use text() to execute raw SQL
            await session.execute(text("ALTER TABLE chapter_chunks ADD COLUMN IF NOT EXISTS embedding vector(384);"))
            await session.commit()
            logger.info("Successfully added 'embedding' column.")
        except Exception as e:
            logger.error(f"Failed to add column: {e}")
            await session.rollback()

if __name__ == "__main__":
    asyncio.run(add_column())
