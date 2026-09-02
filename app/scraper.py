import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import logging

logger = logging.getLogger(__name__)

# One pooled client for the worker's lifetime (standards §8) rather than a
# fresh connection pool + TLS handshake on every bookmark save.
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(follow_redirects=True, timeout=10.0)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def fetch_metadata(url: str) -> dict:
    result = {"title": None, "description": None, "favicon": None}

    if not url.startswith(("http://", "https://")):
        logger.warning("Skipping metadata fetch for non-http URL: %s", url)
        return result

    try:
        resp = await _get_client().get(url)
        if resp.status_code != 200:
            logger.warning(
                "Metadata fetch for %s returned status %d", url, resp.status_code
            )
            return result

        soup = BeautifulSoup(resp.text, "html.parser")

        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            result["title"] = title_tag.string.strip()

        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            result["description"] = meta_desc["content"].strip()

        base_url = str(resp.url)

        icon_link = soup.find("link", rel=lambda v: v and "icon" in v)
        if icon_link and icon_link.get("href"):
            result["favicon"] = urljoin(base_url, icon_link["href"])
        else:
            result["favicon"] = urljoin(base_url, "/favicon.ico")

    except httpx.HTTPError as exc:
        logger.warning("HTTP error fetching metadata for %s: %s", url, exc)
    except Exception as exc:
        logger.exception("Unexpected error scraping %s: %s", url, exc)

    return result
