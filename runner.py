import asyncio
import sys
import json
import os
from app.services.crawler import CrawlerService
from app.core.config import settings

async def main():
    if len(sys.argv) < 2:
        print("Usage: python runner.py <story_url>")
        return

    url = sys.argv[1]
    crawler = CrawlerService()
    
    if not os.path.exists(settings.DATA_DIR):
        os.makedirs(settings.DATA_DIR)

    try:
        story_data = await crawler.crawl_story(url)
        if settings.SAVE_TO_JSON:
            filename = f"{story_data.metadata.title.replace(' ', '_')}.json"
            filepath = settings.DATA_DIR / filename
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(story_data.model_dump(), f, ensure_ascii=False, indent=2)
            print(f"Output saved to {filepath}")
        else:
            print("JSON saving is disabled in settings.")
        
        # Save to Database if configured
        if settings.DATABASE_URL:
            print("Saving to database...")
            await crawler.save_story_to_db(story_data)
            print("Successfully saved to database.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await crawler.close()

if __name__ == "__main__":
    asyncio.run(main())
