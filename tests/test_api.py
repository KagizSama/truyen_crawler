import pytest
from httpx import AsyncClient
from app.main import app
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_search_endpoint():
    # Mock SearchService
    mock_hits = [
        {
            '_source': {
                'story_id': 1,
                'chapter_id': 1,
                'story_title': 'Test Story',
                'chapter_title': 'Chapter 1',
                'content': 'Test content',
                'url': 'http://test.com'
            },
            '_score': 0.9
        }
    ]
    
    with patch('app.api.v1.endpoints.search.SearchService') as mock_search_service_cls:
        mock_instance = AsyncMock()
        mock_instance.hybrid_search.return_value = mock_hits
        mock_search_service_cls.return_value = mock_instance
        
        from httpx import ASGITransport
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/v1/search", params={"q": "test"})
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]['story_title'] == 'Test Story'
        assert data[0]['score'] == 0.9
        
        mock_instance.hybrid_search.assert_called_once_with(
            query="test",
            limit=5,
            story_id=None
        )
        mock_instance.close.assert_called_once()
