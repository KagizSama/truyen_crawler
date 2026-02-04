import json
import asyncio
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, BackgroundTasks, Response
from app.services.crawler import CrawlerService
from app.core.config import settings
from app.schemas.story import CrawlRequest, BatchCrawlRequest
from app.db.session import AsyncSessionLocal
from app.db.models import Job
from sqlalchemy import select
from loguru import logger

router = APIRouter()

async def run_crawl_job(job_id: str, url: str, is_batch: bool = False, limit: int = 10):
    crawler = CrawlerService()
    try:
        await crawler.update_job_status(job_id, status="processing", progress=0)
        
        if not is_batch:
            # Single story
            story_data = await crawler.crawl_story(url, job_id=job_id)
            
            # Save to JSON if configured
            filepath = None
            if settings.SAVE_TO_JSON:
                filename = f"{story_data.metadata.title.replace(' ', '_')}.json"
                filepath = settings.DATA_DIR / filename
                if not settings.DATA_DIR.exists():
                    settings.DATA_DIR.mkdir(parents=True)
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(story_data.model_dump(), f, ensure_ascii=False, indent=2)
            
            # Save to Database if configured
            story_id = None
            if settings.DATABASE_URL:
                story_id = await crawler.save_story_to_db(story_data)
                
                # Trigger Search Integration if DB is enabled
                try:
                    from app.services.search_service import SearchService
                    search_service = SearchService()
                    await search_service.vectorize_and_index_story(story_id, job_id=job_id)
                    await search_service.close()
                    job_status_extra = " (Indexed)"
                except Exception as e:
                    logger.error(f"Post-crawl processing failed for {url}: {e}")
                    job_status_extra = " (Indexing Failed)"
            else:
                job_status_extra = ""
            
            await crawler.update_job_status(
                job_id, 
                status="completed", 
                progress=100, 
                result_path=(str(filepath) if filepath else "DB") + job_status_extra
            )
        else:
            # Batch process
            story_urls = await crawler.get_story_list(url, limit=limit)
            total = len(story_urls)
            await crawler.update_job_status(job_id, progress=5)
            
            async def process_story(s_url: str, idx: int):
                async with crawler.story_semaphore:
                    try:
                        story_data = await crawler.crawl_story(s_url)
                        if settings.SAVE_TO_JSON:
                            filename = f"{story_data.metadata.title.replace(' ', '_')}.json"
                            filepath = settings.DATA_DIR / filename
                            if not settings.DATA_DIR.exists():
                                settings.DATA_DIR.mkdir(parents=True)
                            with open(filepath, "w", encoding="utf-8") as f:
                                json.dump(story_data.model_dump(), f, ensure_ascii=False, indent=2)
                        
                        if settings.DATABASE_URL:
                            story_id = await crawler.save_story_to_db(story_data)
                            
                            # Trigger Search Integration for each story in batch
                            try:
                                from app.services.search_service import SearchService
                                search_service = SearchService()
                                await search_service.vectorize_and_index_story(story_id)
                                await search_service.close()
                            except Exception as e:
                                logger.error(f"Post-crawl indexing failed in batch for {s_url}: {e}")
                        
                        prog = 5 + int(((idx + 1) / total) * 95)
                        await crawler.update_job_status(job_id, progress=prog)
                    except Exception as e:
                        logger.error(f"Failed to crawl {s_url} in batch {job_id}: {e}")

            tasks = [process_story(s_url, i) for i, s_url in enumerate(story_urls)]
            await asyncio.gather(*tasks)
            # Determine final result path for batch
            res_path = "DB_ONLY"
            if settings.SAVE_TO_JSON:
                res_path = str(settings.DATA_DIR)
                
            await crawler.update_job_status(job_id, status="completed", progress=100, result_path=res_path)
            
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        await crawler.update_job_status(job_id, status="failed", error=str(e))
    finally:
        await crawler.close()

@router.post("/crawl")
async def crawl_story(request: CrawlRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as session:
        new_job = Job(id=job_id, url=request.url, type="single", status="pending")
        session.add(new_job)
        await session.commit()
    
    background_tasks.add_task(run_crawl_job, job_id, request.url)
    return {"message": "Crawl started", "job_id": job_id}

@router.post("/batch")
async def batch_crawl(request: BatchCrawlRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as session:
        new_job = Job(id=job_id, url=request.list_url, type="batch", status="pending")
        session.add(new_job)
        await session.commit()
    
    background_tasks.add_task(run_crawl_job, job_id, request.list_url, is_batch=True, limit=request.limit)
    return {"message": "Batch crawl started", "job_id": job_id}

@router.get("/crawler/{job_id}/status")
async def get_job_status(job_id: str):
    async with AsyncSessionLocal() as session:
        stmt = select(Job).where(Job.id == job_id)
        result = await session.execute(stmt)
        job = result.scalar_one_or_none()
        
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        return {
            "id": job.id,
            "url": job.url,
            "type": job.type,
            "status": job.status,
            "progress": job.progress,
            "result_path": job.result_path,
            "error": job.error,
            "created_at": job.created_at,
            "updated_at": job.updated_at
        }

@router.get("/export/{job_id}")
async def export_job_result(job_id: str):
    async with AsyncSessionLocal() as session:
        stmt = select(Job).where(Job.id == job_id)
        result = await session.execute(stmt)
        job = result.scalar_one_or_none()
        
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        if job.status != "completed":
            raise HTTPException(status_code=400, detail=f"Job is {job.status}, not ready for export")
        
        if job.type == "single" and job.result_path and job.result_path != "DB_ONLY":
            try:
                with open(job.result_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Error reading result file: {e}")
        
        return {"message": "Job completed. Results are stored in the database.", "job_id": job.id}
