import hashlib
import logging
import os
from urllib.parse import urlparse

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_EXT_BY_CONTENT_TYPE = {
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
}


def _favicon_filename(bookmark_url: str, content_type: str | None) -> str:
    # Hash the bookmark's own URL (not the favicon URL) so re-saving a
    # bookmark's favicon always overwrites the same file on disk.
    digest = hashlib.sha256(bookmark_url.encode()).hexdigest()[:24]
    ext = _EXT_BY_CONTENT_TYPE.get((content_type or "").split(";")[0].strip().lower())
    if not ext:
        path_ext = os.path.splitext(urlparse(bookmark_url).path)[1].lower()
        ext = path_ext if path_ext and len(path_ext) <= 5 else ".ico"
    return f"{digest}{ext}"


async def save_favicon(bookmark_url: str, favicon_url: str | None) -> str | None:
    """Download `favicon_url` and cache it under FAVICON_DIR.

    Returns the local `/favicons/<file>` path to store on the bookmark row,
    or None if it couldn't be fetched — callers should leave the bookmark
    without a favicon rather than storing a remote URL that may 404 or get
    re-fetched by every browser on every page load.
    """
    if not favicon_url or not favicon_url.startswith(("http://", "https://")):
        return None

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
            resp = await client.get(favicon_url)
            if resp.status_code != 200 or not resp.content:
                logger.warning(
                    "Favicon fetch for %s returned status %d", favicon_url, resp.status_code
                )
                return None
            if len(resp.content) > settings.favicon_max_bytes:
                logger.warning(
                    "Favicon at %s exceeds %d bytes; skipping",
                    favicon_url,
                    settings.favicon_max_bytes,
                )
                return None

            filename = _favicon_filename(bookmark_url, resp.headers.get("content-type"))
            os.makedirs(settings.favicon_dir, exist_ok=True)
            with open(os.path.join(settings.favicon_dir, filename), "wb") as f:
                f.write(resp.content)
            return f"/favicons/{filename}"

    except httpx.HTTPError as exc:
        logger.warning("HTTP error fetching favicon %s: %s", favicon_url, exc)
        return None
    except Exception:
        logger.exception("Unexpected error saving favicon for %s", bookmark_url)
        return None
