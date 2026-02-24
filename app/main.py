import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.database import init_db, get_db
from app.models import BookmarkCreate, BookmarkUpdate, BookmarkResponse, TagCount
from app.scraper import fetch_metadata
from app.ai import generate_tags
from collections import Counter


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    app.state.db = await get_db()
    yield
    if hasattr(app.state, "db"):
        await app.state.db.close()


app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


def _row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "url": row["url"],
        "title": row["title"],
        "description": row["description"],
        "favicon": row["favicon"],
        "tags": row["tags"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@app.post("/api/bookmarks", status_code=201)
async def create_bookmark(request: Request, bookmark: BookmarkCreate):
    db = request.app.state.db

    # Check for duplicate
    existing = await db.execute("SELECT id FROM bookmarks WHERE url = ?", (bookmark.url,))
    if await existing.fetchone():
        raise HTTPException(status_code=409, detail="URL already exists")

    # Scrape metadata
    metadata = await fetch_metadata(bookmark.url)
    title = metadata.get("title")
    description = metadata.get("description")
    favicon = metadata.get("favicon")

    # AI auto-tag
    tags_list = await generate_tags(bookmark.url, title, description)
    tags = ",".join(tags_list)

    cursor = await db.execute(
        "INSERT INTO bookmarks (url, title, description, favicon, tags) VALUES (?, ?, ?, ?, ?)",
        (bookmark.url, title, description, favicon, tags),
    )
    await db.commit()

    row = await db.execute("SELECT * FROM bookmarks WHERE id = ?", (cursor.lastrowid,))
    result = await row.fetchone()
    return _row_to_dict(result)


@app.get("/api/bookmarks")
async def list_bookmarks(
    request: Request,
    search: str | None = None,
    tag: str | None = None,
):
    db = request.app.state.db
    query = "SELECT * FROM bookmarks WHERE 1=1"
    params = []

    if search:
        query += " AND (title LIKE ? OR url LIKE ? OR description LIKE ? OR tags LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if tag:
        query += " AND (',' || tags || ',' LIKE ?)"
        params.append(f"%,{tag},%")

    query += " ORDER BY created_at DESC"

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


@app.put("/api/bookmarks/{bookmark_id}")
async def update_bookmark(request: Request, bookmark_id: int, update: BookmarkUpdate):
    db = request.app.state.db

    row = await db.execute("SELECT * FROM bookmarks WHERE id = ?", (bookmark_id,))
    existing = await row.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    fields = []
    params = []
    if update.title is not None:
        fields.append("title = ?")
        params.append(update.title)
    if update.description is not None:
        fields.append("description = ?")
        params.append(update.description)
    if update.tags is not None:
        fields.append("tags = ?")
        params.append(update.tags)

    if fields:
        fields.append("updated_at = CURRENT_TIMESTAMP")
        params.append(bookmark_id)
        await db.execute(
            f"UPDATE bookmarks SET {', '.join(fields)} WHERE id = ?", params
        )
        await db.commit()

    row = await db.execute("SELECT * FROM bookmarks WHERE id = ?", (bookmark_id,))
    result = await row.fetchone()
    return _row_to_dict(result)


@app.delete("/api/bookmarks/{bookmark_id}", status_code=204)
async def delete_bookmark(request: Request, bookmark_id: int):
    delete_password = os.environ.get("DELETE_PASSWORD")
    if delete_password:
        provided = request.headers.get("X-Delete-Password", "")
        if provided != delete_password:
            raise HTTPException(status_code=401, detail="Invalid password")

    db = request.app.state.db
    row = await db.execute("SELECT id FROM bookmarks WHERE id = ?", (bookmark_id,))
    if not await row.fetchone():
        raise HTTPException(status_code=404, detail="Bookmark not found")

    await db.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
    await db.commit()
    return Response(status_code=204)


@app.get("/api/tags")
async def get_tags(request: Request):
    db = request.app.state.db
    cursor = await db.execute("SELECT tags FROM bookmarks WHERE tags != '' AND tags IS NOT NULL")
    rows = await cursor.fetchall()

    counter = Counter()
    for row in rows:
        for tag in row["tags"].split(","):
            tag = tag.strip()
            if tag:
                counter[tag] += 1

    return [{"tag": tag, "count": count} for tag, count in counter.most_common()]
