import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.config import settings
from app.db import init_db, get_db, check_and_record_rate_limit
from app.models import BookmarkCreate, BookmarkUpdate, BookmarkResponse, TagCount
from app.scraper import fetch_metadata
from app.services.llm import generate_tags
from collections import Counter

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("bookmark")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up: initializing database")
    await init_db()
    app.state.db = await get_db()
    logger.info("Startup complete")
    yield
    logger.info("Shutting down")
    if hasattr(app.state, "db"):
        await app.state.db.close()


app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["prefix"] = settings.root_path


@app.get("/health")
async def health():
    return JSONResponse(content={"status": "ok"})


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s -> %d (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # Client/handled errors (404, 409, 401, ...) — log at warning, not as crashes.
    logger.warning(
        "%s %s -> %d: %s",
        request.method,
        request.url.path,
        exc.status_code,
        exc.detail,
    )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(
        "Unhandled exception on %s %s", request.method, request.url.path
    )
    return JSONResponse(
        status_code=500, content={"detail": "Internal server error"}
    )


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


def _client_ip(request: Request) -> str:
    # Gunicorn is bound to a unix socket behind nginx, so request.client is
    # frequently empty/wrong — read the proxy headers nginx sets instead.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip
    return request.client.host if request.client else "unknown"


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

    # Fetches an arbitrary URL and calls the paid OpenRouter API, so cap it
    # per-IP before doing any of that work.
    allowed = await check_and_record_rate_limit(
        db,
        ip=_client_ip(request),
        route="create_bookmark",
        limit=settings.rate_limit_per_minute,
        window_seconds=settings.rate_limit_window_seconds,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests — please slow down and try again in a minute.",
        )

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
    logger.info("Created bookmark %d: %s", result["id"], bookmark.url)
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
    delete_password = settings.delete_password
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
    logger.info("Deleted bookmark %d", bookmark_id)
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
