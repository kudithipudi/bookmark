import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.llm import generate_tags
from app.config import settings


async def test_generate_tags_success():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "python, web, tutorial"}}]
    }

    with patch.object(settings, "openrouter_api_key", "test-key"):
        with patch("app.services.llm.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post.return_value = mock_response
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            tags = await generate_tags("https://example.com", "Python Tutorial", "Learn Python")

    assert "python" in tags
    assert "web" in tags
    assert "tutorial" in tags


async def test_generate_tags_no_api_key():
    with patch.object(settings, "openrouter_api_key", None):
        tags = await generate_tags("https://example.com", "Test", "Test")
    assert tags == []


async def test_generate_tags_api_error():
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.json.return_value = {"error": "Internal server error"}

    with patch.object(settings, "openrouter_api_key", "test-key"):
        with patch("app.services.llm.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.post.return_value = mock_response
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            tags = await generate_tags("https://example.com", "Test", "Test")

    assert tags == []
