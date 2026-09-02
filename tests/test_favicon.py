import os
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services.favicon import save_favicon


async def test_save_favicon_success(tmp_path):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.content = b"\x00\x01fake-icon-bytes"
    mock_response.headers = {"content-type": "image/x-icon"}

    with patch.object(settings, "favicon_dir", str(tmp_path)), \
         patch("app.services.favicon._get_client") as MockClient:
        instance = AsyncMock()
        instance.get.return_value = mock_response
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        result = await save_favicon("https://example.com", "https://example.com/favicon.ico")

    assert result is not None
    assert result.startswith("/favicons/")
    assert result.endswith(".ico")
    saved_file = os.path.join(str(tmp_path), result.removeprefix("/favicons/"))
    assert os.path.exists(saved_file)
    with open(saved_file, "rb") as f:
        assert f.read() == b"\x00\x01fake-icon-bytes"


async def test_save_favicon_none_url():
    assert await save_favicon("https://example.com", None) is None


async def test_save_favicon_404(tmp_path):
    mock_response = AsyncMock()
    mock_response.status_code = 404
    mock_response.content = b""

    with patch.object(settings, "favicon_dir", str(tmp_path)), \
         patch("app.services.favicon._get_client") as MockClient:
        instance = AsyncMock()
        instance.get.return_value = mock_response
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        result = await save_favicon("https://example.com", "https://example.com/favicon.ico")

    assert result is None
    assert os.listdir(str(tmp_path)) == []


async def test_save_favicon_too_large(tmp_path):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.content = b"x" * (10 * 1024 * 1024)
    mock_response.headers = {"content-type": "image/png"}

    with patch.object(settings, "favicon_dir", str(tmp_path)), \
         patch("app.services.favicon._get_client") as MockClient:
        instance = AsyncMock()
        instance.get.return_value = mock_response
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        result = await save_favicon("https://example.com", "https://example.com/favicon.ico")

    assert result is None


async def test_save_favicon_stable_filename(tmp_path):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.content = b"icon-bytes"
    mock_response.headers = {"content-type": "image/png"}

    with patch.object(settings, "favicon_dir", str(tmp_path)), \
         patch("app.services.favicon._get_client") as MockClient:
        instance = AsyncMock()
        instance.get.return_value = mock_response
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        first = await save_favicon("https://example.com", "https://example.com/a.ico")
        second = await save_favicon("https://example.com", "https://example.com/b.png")

    # Filename is derived from the bookmark URL, not the favicon URL, so a
    # re-save always overwrites the same file instead of accumulating stale ones.
    assert first == second
    assert len(os.listdir(str(tmp_path))) == 1
