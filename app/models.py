from urllib.parse import urlparse

from pydantic import BaseModel, field_validator


def _require_http_url(value: str) -> str:
    """Accept only real http(s) URLs. The create endpoint fetches this URL
    server-side and hands it to the tagging API, so a bare string, a
    `javascript:` payload, or an `ftp://`/`file://` scheme must be rejected
    before any of that runs."""
    candidate = value.strip()
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("must be a valid http:// or https:// URL")
    return candidate


class BookmarkCreate(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        return _require_http_url(v)


class BookmarkUpdate(BaseModel):
    url: str | None = None
    title: str | None = None
    description: str | None = None
    tags: str | None = None

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str | None) -> str | None:
        return v if v is None else _require_http_url(v)


class BookmarkResponse(BaseModel):
    id: int
    url: str
    title: str | None = None
    description: str | None = None
    favicon: str | None = None
    tags: str = ""
    is_favorite: bool = False
    created_at: str | None = None
    updated_at: str | None = None


class TagCount(BaseModel):
    tag: str
    count: int
