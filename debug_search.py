import asyncio
from app.services.search_service import SearchService

async def debug_search():
    service = SearchService()
    query = "Ngu Dung Ca"
    print(f"Searching for: {query}")
    
    hits = await service.hybrid_search(query, limit=10)
    
    print(f"Found {len(hits)} hits.")
    for i, hit in enumerate(hits):
        source = hit['_source']
        print(f"\n--- Hit {i+1} (Score: {hit.get('_score')}) ---")
        print(f"Story: {source.get('story_title')}")
        print(f"Chapter: {source.get('chapter_title')}")
        print(f"Content Preview: {source.get('content')[:200]}...")
        
    await service.close()

if __name__ == "__main__":
    asyncio.run(debug_search())
