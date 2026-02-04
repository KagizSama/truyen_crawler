import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.agent_service import AgentService, ChatResponse
from app.schemas.agent import SourceNode

@pytest.mark.asyncio
async def test_agent_chat_flow():
    # Mock settings
    with patch("app.services.agent_service.settings") as mock_settings:
        mock_settings.GEMINI_API_KEY = "fake_key"
        mock_settings.GEMINI_MODEL = "gemini-1.5-flash"
        
        # Mock SearchService
        with patch("app.services.agent_service.SearchService") as MockSearch:
            mock_search_instance = MockSearch.return_value
            mock_search_instance.hybrid_search = AsyncMock(return_value=[
                {
                    "_source": {
                        "story_title": "Test Story",
                        "chapter_title": "Chapter 1",
                        "content": "This is a test content.",
                        "story_id": 1,
                        "chapter_id": 1
                    },
                    "_score": 0.9
                }
            ])
            
            # Mock Gemini
            with patch("app.services.agent_service.genai") as mock_genai:
                 # Mock GenerativeModel instance
                mock_model = MagicMock()
                mock_model.generate_content.return_value.text = "This is a generated answer."
                mock_genai.GenerativeModel.return_value = mock_model
                
                service = AgentService()
                
                # Test chat
                response = await service.chat("Hello")
                
                assert isinstance(response, ChatResponse)
                assert response.answer == "This is a generated answer."
                assert len(response.sources) == 1
                assert response.sources[0].story_title == "Test Story"
                
                # Verify prompt construction (indirectly)
                mock_model.generate_content.assert_called_once()
                args, _ = mock_model.generate_content.call_args
                prompt = args[0]
                assert "Test Story" in prompt
                assert "This is a test content" in prompt
