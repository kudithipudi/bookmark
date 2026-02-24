import pytest
from unittest.mock import AsyncMock, patch
from app.scraper import fetch_metadata
import httpx


SAMPLE_HTML = """
<html>
<head>
    <title>Example Page</title>
    <meta name="description" content="An example description">
    <link rel="icon" href="/favicon.ico">
</head>
<body></body>
</html>
"""


async def test_fetch_metadata_success():
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.text = SAMPLE_HTML
    mock_response.url = httpx.URL("https://example.com/page")

    with patch("app.scraper.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.get.return_value = mock_response
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        result = await fetch_metadata("https://example.com/page")

    assert result["title"] == "Example Page"
    assert result["description"] == "An example description"
    assert "favicon" in result


async def test_fetch_metadata_timeout():
    with patch("app.scraper.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.get.side_effect = httpx.TimeoutException("timeout")
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        result = await fetch_metadata("https://example.com")

    assert result["title"] is None
    assert result["description"] is None


async def test_fetch_metadata_invalid_url():
    result = await fetch_metadata("not-a-url")
    assert result["title"] is None
    assert result["description"] is None
