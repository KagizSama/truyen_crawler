import asyncio
import sys
import json
import os
from app.services.crawler import CrawlerService
from app.core.config import settings

async def main():
    if len(sys.argv) < 2:
        print("Usage: python batch_runner.py <list_url> [limit]")
        return

    list_url = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    
    crawler = CrawlerService()
    
    if not os.path.exists(settings.DATA_DIR):
        os.makedirs(settings.DATA_DIR)

    try:
        story_urls = await crawler.get_story_list(list_url, limit)
        print(f"Found {len(story_urls)} stories. Starting batch crawl...")
        
        async def process_story(url: str):
            async with crawler.story_semaphore:
                try:
                    story_data = await crawler.crawl_story(url)
                    filename = f"{story_data.metadata.title.replace(' ', '_')}.json"
                    filepath = settings.DATA_DIR / filename
                    
                    with open(filepath, "w", encoding="utf-8") as f:
                        json.dump(story_data.model_dump(), f, ensure_ascii=False, indent=2)
                        
                    print(f"Successfully crawled: {story_data.metadata.title}")
                except Exception as e:
                    print(f"Failed to crawl {url}: {e}")

        tasks = [process_story(url) for url in story_urls]
        await asyncio.gather(*tasks)
                
    except Exception as e:
        print(f"Batch Error: {e}")
    finally:
        await crawler.close()

if __name__ == "__main__":
    asyncio.run(main())
