import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.search_service import SearchService

@pytest.fixture
def mock_search_service():
    with patch('app.services.search_service.SentenceTransformer') as mock_st, \
         patch('app.services.search_service.AsyncElasticsearch') as mock_es:
        
        # Mock SentenceTransformer
        mock_model = MagicMock()
        import numpy as np
        mock_model.encode.return_value = np.array([[0.1] * 384])
        mock_st.return_value = mock_model
        
        # Mock AsyncElasticsearch
        mock_es_instance = AsyncMock()
        mock_es_instance.indices.exists.return_value = True
        mock_es_instance.search.return_value = {
            'hits': {
                'hits': [
                    {
                        '_source': {
                            'story_id': 1,
                            'chapter_id': 1,
                            'story_title': 'Test Story',
                            'content': 'Test content',
                            'url': 'http://test.com'
                        },
                        '_score': 1.0
                    }
                ]
            }
        }
        mock_es.return_value = mock_es_instance
        
        service = SearchService()
        yield service, mock_es_instance, mock_model

@pytest.mark.asyncio
async def test_generate_embeddings(mock_search_service):
    service, _, mock_model = mock_search_service
    embeddings = await service.generate_embeddings(["test text"])
    
    assert len(embeddings) == 1
    assert len(embeddings[0]) == 384
    mock_model.encode.assert_called_once()

@pytest.mark.asyncio
async def test_hybrid_search(mock_search_service):
    service, mock_es_instance, _ = mock_search_service
    
    # Needs ELASTICSEARCH_URL to be truthy in settings for this to run
    with patch('app.services.search_service.settings') as mock_settings:
        mock_settings.ELASTICSEARCH_URL = "http://localhost:9200"
        mock_settings.ELASTICSEARCH_INDEX = "test_index"
        
        results = await service.hybrid_search("query")
        
        assert len(results) == 1
        assert results[0]['_source']['story_title'] == 'Test Story'
        mock_es_instance.search.assert_called_once()

@pytest.mark.asyncio
async def test_create_index_if_not_exists(mock_search_service):
    service, mock_es_instance, _ = mock_search_service
    mock_es_instance.indices.exists.return_value = False
    
    await service.create_index_if_not_exists()
    
    mock_es_instance.indices.create.assert_called_once()
