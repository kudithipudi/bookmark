import httpx
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services import llm
from app.services.llm import close_client, generate_tags
from app.config import settings


async def test_generate_tags_success():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "python, web, tutorial"}}]
    }

    with patch.object(settings, "openrouter_api_key", "test-key"):
        with patch("app.services.llm._get_client") as MockClient:
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
        with patch("app.services.llm._get_client") as MockClient:
            instance = AsyncMock()
            instance.post.return_value = mock_response
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            tags = await generate_tags("https://example.com", "Test", "Test")

    assert tags == []


async def test_generate_tags_request_exception():
    """A network-level exception (not just a bad status) must be caught and
    logged, returning an empty tag list rather than propagating (lines 91-96)."""

    class _RaisingClient:
        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("connection refused")

    with patch.object(settings, "openrouter_api_key", "test-key"):
        with patch("app.services.llm._get_client", return_value=_RaisingClient()):
            tags = await generate_tags("https://example.com", "Test", "Test")

    assert tags == []


def test_get_client_creates_and_reuses_instance():
    """_get_client lazily builds one pooled AsyncClient and reuses it on
    subsequent calls as long as it isn't closed (lines 19-21)."""
    llm._client = None
    try:
        first = llm._get_client()
        assert isinstance(first, httpx.AsyncClient)
        assert not first.is_closed

        second = llm._get_client()
        assert second is first
    finally:
        llm._client = None


async def test_get_client_rebuilds_after_close():
    """Once the pooled client is closed, the next _get_client() call must
    build a fresh one rather than reusing the closed instance."""
    llm._client = None
    try:
        first = llm._get_client()
        await first.aclose()
        assert first.is_closed

        second = llm._get_client()
        assert second is not first
        assert not second.is_closed
        await second.aclose()
    finally:
        llm._client = None


async def test_close_client_closes_open_client():
    """close_client() closes an open pooled client and resets the module
    global to None (lines 26-28)."""
    llm._client = None
    client = llm._get_client()
    assert not client.is_closed

    await close_client()

    assert llm._client is None
    assert client.is_closed


async def test_close_client_noop_when_already_none():
    """close_client() is a safe no-op when there is no pooled client yet."""
    llm._client = None

    await close_client()

    assert llm._client is None
