import asyncio
import httpx
from bs4 import BeautifulSoup
from loguru import logger
from typing import List, Optional
from app.core.config import settings
from app.core.exceptions import NetworkError, ParsingError
from app.schemas.story import StoryMetadata, Chapter, StoryData
from app.db.session import AsyncSessionLocal
from app.db.models import Story, Chapter as DBChapter, ChapterChunk, Job
from app.services.processor import TextProcessor
from app.services.search_service import SearchService
from sqlalchemy.future import select
from sqlalchemy import update

class CrawlerService:
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=settings.REQUEST_TIMEOUT,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
        self.semaphore = asyncio.Semaphore(settings.CONCURRENT_REQUESTS)
        self.story_semaphore = asyncio.Semaphore(2) # Limit concurrent stories to avoid blocks

    async def _get(self, url: str) -> str:
        async with self.semaphore:
            for attempt in range(settings.RETRIES):
                try:
                    response = await self.client.get(url)
                    response.raise_for_status()
                    return response.text
                except (httpx.HTTPStatusError, httpx.RequestError) as e:
                    logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                    if attempt == settings.RETRIES - 1:
                        raise NetworkError(f"Failed to fetch {url} after {settings.RETRIES} attempts")
                    await asyncio.sleep(settings.RETRY_BACKOFF ** attempt)
        return ""

    async def get_metadata(self, url: str) -> StoryMetadata:
        html = await self._get(url)
        soup = BeautifulSoup(html, "lxml")
        
        try:
            title = soup.find("h3", class_="title").text.strip()
            info_div = soup.find("div", class_="info")
            
            author = info_div.find("a", href=lambda x: x and "/tac-gia/" in x).text.strip()
            genres = [a.text.strip() for a in info_div.find_all("a", href=lambda x: x and "/the-loai/" in x)]
            
            # Status is usually the text after the 'Trạng thái' header
            status_elem = info_div.find("span", class_="text-success") or info_div.find("span", class_="text-primary")
            status = status_elem.text.strip() if status_elem else "Unknown"
            
            desc_div = soup.find("div", class_="desc-text")
            description = desc_div.get_text(separator="\n").strip() if desc_div else ""
            
            return StoryMetadata(
                title=title,
                author=author,
                genres=genres,
                description=description,
                status=status,
                url=url
            )
        except Exception as e:
            logger.error(f"Error parsing metadata for {url}: {e}")
            raise ParsingError(f"Could not parse metadata from {url}")

    async def get_chapter_list(self, base_url: str) -> List[Chapter]:
        chapters = []
        current_url = base_url
        page = 1
        
        while current_url:
            logger.info(f"Fetching chapter list from page {page}: {current_url}")
            html = await self._get(current_url)
            soup = BeautifulSoup(html, "lxml")
            
            try:
                list_chapter = soup.find("div", id="list-chapter")
                if not list_chapter:
                    break
                    
                links = list_chapter.find_all("a")
                for a in links:
                    if "chuong-" in a["href"]:
                        chapters.append(Chapter(
                            title=a.text.strip(),
                            url=a["href"],
                            order=len(chapters) + 1
                        ))
                
                # Handle pagination
                pagination = soup.find("ul", class_="pagination")
                next_page = None
                if pagination:
                    # Look for "Trang tiếp" in text or the right arrow icon
                    for a in pagination.find_all("a"):
                        if "Trang tiếp" in a.get_text() or a.find("span", class_="glyphicon-menu-right"):
                            next_page = a["href"]
                            break
                
                if next_page and next_page != current_url:
                    current_url = next_page
                    page += 1
                else:
                    current_url = None
                    
            except Exception as e:
                logger.error(f"Error parsing chapter list for {current_url}: {e}")
                break
                
        return chapters

    async def get_story_list(self, list_url: str, limit: int = 10) -> List[str]:
        story_urls = []
        current_url = list_url
        page = 1
        
        while current_url and len(story_urls) < limit:
            logger.info(f"Fetching story list from page {page}: {current_url}")
            html = await self._get(current_url)
            soup = BeautifulSoup(html, "lxml")
            
            try:
                # Standard truyenfull list structure
                list_truyen = soup.find("div", class_="list-truyen") or soup.find("div", id="list-page")
                if not list_truyen:
                    logger.warning(f"No story list found on {current_url}")
                    break
                    
                links = list_truyen.find_all("h3", class_="truyen-title")
                for h3 in links:
                    a = h3.find("a")
                    if a and a.has_attr("href"):
                        story_urls.append(a["href"])
                        if len(story_urls) >= limit:
                            break
                
                if len(story_urls) >= limit:
                    break
                    
                # Handle pagination if limit not reached
                pagination = soup.find("ul", class_="pagination")
                next_page = None
                if pagination:
                    next_link = pagination.find("a", string=lambda x: x and ("Trang tiếp" in x or "»" in x))
                    if next_link:
                        next_page = next_link["href"]
                
                if next_page and next_page != current_url:
                    current_url = next_page
                    page += 1
                else:
                    current_url = None
            except Exception as e:
                logger.error(f"Error parsing story list for {current_url}: {e}")
                break
                
        return story_urls[:limit]

    async def get_chapter_content(self, chapter: Chapter) -> str:
        html = await self._get(chapter.url)
        soup = BeautifulSoup(html, "lxml")
        
        try:
            content_div = soup.find("div", id="chapter-c")
            if not content_div:
                raise ParsingError(f"Content div not found for {chapter.url}")
            
            # Remove ads or unwanted elements if necessary
            for ads in content_div.find_all(["div", "ins"]):
                ads.decompose()
                
            return content_div.get_text(separator="\n").strip()
        except Exception as e:
            logger.error(f"Error parsing chapter content for {chapter.url}: {e}")
            raise ParsingError(f"Could not parse content from {chapter.url}")

    async def update_job_status(self, job_id: str, status: str = None, progress: int = None, error: str = None, result_path: str = None):
        if not job_id:
            return
        async with AsyncSessionLocal() as session:
            try:
                values = {}
                if status:
                    values['status'] = status
                if progress is not None:
                    values['progress'] = progress
                if error:
                    values['error'] = error
                if result_path:
                    values['result_path'] = result_path
                
                if values:
                    await session.execute(
                        update(Job).where(Job.id == job_id).values(**values)
                    )
                    await session.commit()
            except Exception as e:
                logger.error(f"Failed to update job {job_id}: {e}")

    async def crawl_story(self, url: str, job_id: str = None) -> StoryData:
        logger.info(f"Starting crawl for {url}")
        
        # 1. Fetch Metadata
        metadata = await self.get_metadata(url)
        await self.update_job_status(job_id, progress=5) # Metadata fetched
        
        # 2. Fetch Chapter List
        chapter_list_data = await self.get_chapter_list(url) # List of Chapter objects
        total_total = len(chapter_list_data)
        
        # --- SMART RESUME: Check DB for existing chapters ---
        existing_chapter_urls = set()
        if settings.DATABASE_URL:
            async with AsyncSessionLocal() as session:
                # Find Story ID first
                story_stmt = select(Story.id).where(Story.url == url)
                story_res = await session.execute(story_stmt)
                story_id = story_res.scalar_one_or_none()
                
                if story_id:
                    # Get chapters that have content
                    chap_stmt = select(DBChapter.url).where(
                        DBChapter.story_id == story_id,
                        DBChapter.content.isnot(None),
                        DBChapter.content != ""
                    )
                    chap_res = await session.execute(chap_stmt)
                    existing_chapter_urls = set(chap_res.scalars().all())
        
        # Filter: Only crawl chapters NOT in existing_chapter_urls
        chapters_to_crawl = [c for c in chapter_list_data if c.url not in existing_chapter_urls]
        skipped_count = total_total - len(chapters_to_crawl)
        
        if skipped_count > 0:
            logger.info(f"Smart Resume: Skipping {skipped_count} chapters already in DB.")
            
        total_to_crawl = len(chapters_to_crawl)
        logger.info(f"Found {total_total} total chapters. To crawl: {total_to_crawl}. Fetching in batches of {settings.BATCH_SIZE}...")
        await self.update_job_status(job_id, progress=10)
        
        # 3. Process MISSING Chapters in Batches
        all_chapters_with_content = [] # We still want to return full data if possible, but for now focus on crawling
        
        # Note: If we skip, we still need the metadata of skipped chapters for the final StoryData object?
        # For simplicity, we only crawl missing ones, but the final StoryData will only have missing ones 
        # unless we merge. But the main goal is DB persistence.
        
        for i in range(0, total_to_crawl, settings.BATCH_SIZE):
            batch_chapters = chapters_to_crawl[i:i + settings.BATCH_SIZE]
            
            tasks = [self._fetch_and_update_chapter(chapter) for chapter in batch_chapters]
            await asyncio.gather(*tasks)
            all_chapters_with_content.extend(batch_chapters)
            
            # Update progress based on total_total
            completed = skipped_count + len(all_chapters_with_content)
            progress = 10 + int((completed / total_total) * 80)
            await self.update_job_status(job_id, progress=progress)
            
            if i + settings.BATCH_SIZE < total_to_crawl and settings.CHAPTER_DELAY > 0:
                logger.info(f"Batch completed. Sleeping {settings.CHAPTER_DELAY}s before next batch...")
                await asyncio.sleep(settings.CHAPTER_DELAY)
            
        # Merge with existing data for the return object (optional but good for JSON save)
        # However, for DB save, we only need to pass chapters_to_crawl to save_story_to_db?
        # Actually save_story_to_db logic will handle merging/upserting.
        
        story_data = StoryData(
            metadata=metadata,
            chapters=all_chapters_with_content, # Only return what we caved this time
            total_chapters=total_total
        )
        
        # Final update
        await self.update_job_status(job_id, progress=95) # Crawl done, saving next
        
        return story_data

    async def _fetch_and_update_chapter(self, chapter: Chapter):
        try:
            chapter.content = await self.get_chapter_content(chapter)
            logger.info(f"Successfully fetched {chapter.title}")
        except Exception as e:
            logger.error(f"Failed to fetch content for {chapter.title}: {e}")
            chapter.content = f"[Error fetching content: {str(e)}]"

    async def save_story_to_db(self, story_data: StoryData):
        async with AsyncSessionLocal() as session:
            try:
                # 1. Save or Update Story
                stmt = select(Story).where(Story.url == story_data.metadata.url)
                result = await session.execute(stmt)
                db_story = result.scalar_one_or_none()
                
                if not db_story:
                    db_story = Story(
                        title=story_data.metadata.title,
                        author=story_data.metadata.author,
                        genres=story_data.metadata.genres,
                        description=story_data.metadata.description,
                        status=story_data.metadata.status,
                        url=story_data.metadata.url
                    )
                    session.add(db_story)
                else:
                    db_story.title = story_data.metadata.title
                    db_story.author = story_data.metadata.author
                    db_story.genres = story_data.metadata.genres
                    db_story.description = story_data.metadata.description
                    db_story.status = story_data.metadata.status

                await session.flush() # Get story ID
                
                # 2. Get all existing chapters for this story at once
                chapter_stmt = select(DBChapter).where(DBChapter.story_id == db_story.id)
                chapter_result = await session.execute(chapter_stmt)
                existing_chapters = {c.url: c for c in chapter_result.scalars().all()}
                
                all_chunks_to_add = []
                chapter_ids_to_clear = []

                # 3. Process Chapters
                for chapter_data in story_data.chapters:
                    cleaned_content = TextProcessor.clean_text(chapter_data.content)
                    chunks = TextProcessor.chunk_text(cleaned_content)
                    
                    db_chapter = existing_chapters.get(chapter_data.url)
                    
                    if not db_chapter:
                        db_chapter = DBChapter(
                            story_id=db_story.id,
                            title=chapter_data.title,
                            url=chapter_data.url,
                            content=cleaned_content,
                            order=chapter_data.order
                        )
                        session.add(db_chapter)
                    else:
                        db_chapter.title = chapter_data.title
                        db_chapter.content = cleaned_content
                        db_chapter.order = chapter_data.order
                        chapter_ids_to_clear.append(db_chapter.id)
                    
                    # Store chunks for bulk addition after flush
                    # We need the ID, so we'll handle this in a second pass for new chapters
                    chapter_data._db_chapter = db_chapter # Temporary storage
                    chapter_data._chunks = chunks

                await session.flush() # Ensure all chapters have IDs

                # 4. Bulk manage Chunks
                # Delete existing chunks for updated chapters
                if chapter_ids_to_clear:
                    from sqlalchemy import delete
                    await session.execute(
                        delete(ChapterChunk).where(ChapterChunk.chapter_id.in_(chapter_ids_to_clear))
                    )

                # Collect and add all chunks at once
                chunks_to_add = []
                for chapter_data in story_data.chapters:
                    db_chapter = chapter_data._db_chapter
                    for idx, chunk_content in enumerate(chapter_data._chunks):
                        chunks_to_add.append(ChapterChunk(
                            chapter_id=db_chapter.id,
                            chunk_content=chunk_content,
                            chunk_index=idx
                        ))
                
                session.add_all(chunks_to_add)
                
                await session.commit()
                logger.info(f"Successfully optimized save for story '{story_data.metadata.title}' with {len(story_data.chapters)} chapters.")
                return db_story.id
            except Exception as e:
                await session.rollback()
                logger.error(f"Error saving story to DB: {e}")
                raise

    async def close(self):
        await self.client.aclose()
