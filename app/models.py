from pydantic import BaseModel, HttpUrl
from datetime import datetime


class BookmarkCreate(BaseModel):
    url: str


class BookmarkUpdate(BaseModel):
    url: str | None = None
    title: str | None = None
    description: str | None = None
    tags: str | None = None


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
