import asyncio
import logging
import os
import time
from collections import Counter
from contextlib import asynccontextmanager
from datetime import date
from urllib.parse import urlparse
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.config import settings
from app.db import init_db, get_db, check_and_record_rate_limit
from app.models import BookmarkCreate, BookmarkUpdate, BookmarkResponse, TagCount
from app import scraper
from app.scraper import fetch_metadata
from app.services import favicon as favicon_service
from app.services import llm
from app.services.favicon import save_favicon
from app.services.llm import generate_tags
from app.services.embeddings import embed_bookmark, embed_query, warmup_embeddings
from app.services.semantic_index import (
    get_semantic_index,
    invalidate_index,
)
from app.services.linkcheck import (
    active_run,
    create_run,
    latest_run,
    run_link_check,
)

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
    # Warm the embedding model in the background: first load can take seconds
    # (model download on a cold host) and must not block startup or the first
    # search that happens to need it.
    app.state.embed_warmup_task = asyncio.create_task(warmup_embeddings())
    logger.info("Startup complete")
    yield
    logger.info("Shutting down")
    task = getattr(app.state, "embed_warmup_task", None)
    if task:
        task.cancel()
    if hasattr(app.state, "db"):
        await app.state.db.close()
    await llm.close_client()
    await scraper.close_client()
    await favicon_service.close_client()


app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
os.makedirs(settings.favicon_dir, exist_ok=True)
app.mount("/favicons", StaticFiles(directory=settings.favicon_dir), name="favicons")
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


@app.get("/analytics")
async def analytics_page(request: Request):
    return templates.TemplateResponse("analytics.html", {"request": request})


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
        "link_status": row["link_status"],
        "link_status_code": row["link_status_code"],
        "link_final_url": row["link_final_url"],
        "link_checked_at": row["link_checked_at"],
        "link_fail_count": row["link_fail_count"] or 0,
    }


def _require_admin(request: Request) -> None:
    """Gate for admin-only routes. If no ADMIN_PASSWORD/DELETE_PASSWORD is
    configured (e.g. local dev), the routes are open — same convention as
    the delete endpoint."""
    pw = settings.admin_password
    if pw and request.headers.get("X-Admin-Password", "") != pw:
        raise HTTPException(status_code=401, detail="Invalid password")


_RUN_FIELDS = (
    "id", "started_at", "finished_at", "total", "checked",
    "ok", "broken", "moved", "uncertain", "error",
)


def _run_to_dict(row) -> dict | None:
    return {k: row[k] for k in _RUN_FIELDS} if row is not None else None


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
    # Download and cache the favicon locally instead of storing the remote
    # URL, so we serve it ourselves (no repeat fetches, no surprise 404s).
    favicon = await save_favicon(bookmark.url, metadata.get("favicon"))

    # AI auto-tag
    tags_list = await generate_tags(bookmark.url, title, description)
    tags = ",".join(tags_list)

    embedding = await embed_bookmark(title, description, tags)

    cursor = await db.execute(
        "INSERT INTO bookmarks (url, title, description, favicon, tags, embedding) VALUES (?, ?, ?, ?, ?, ?)",
        (bookmark.url, title, description, favicon, tags, embedding),
    )
    await db.commit()
    invalidate_index(app.state)

    row = await db.execute("SELECT * FROM bookmarks WHERE id = ?", (cursor.lastrowid,))
    result = await row.fetchone()
    logger.info("Created bookmark %d: %s", result["id"], bookmark.url)
    return _row_to_dict(result)


@app.get("/api/bookmarks")
async def list_bookmarks(
    request: Request,
    search: str | None = None,
    tag: str | None = None,
    status: str | None = None,
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

    # Link-health filter, populated by the bulk checker. "broken" is only the
    # links that have failed the threshold number of consecutive sweeps;
    # "review" is everything else the checker couldn't confirm as fine.
    if status:
        threshold = settings.link_check_broken_threshold
        if status == "broken":
            query += " AND link_status = 'broken' AND COALESCE(link_fail_count, 0) >= ?"
            params.append(threshold)
        elif status == "review":
            query += (
                " AND (link_status IN ('uncertain', 'moved')"
                " OR (link_status = 'broken' AND COALESCE(link_fail_count, 0) < ?))"
            )
            params.append(threshold)
        elif status == "ok":
            query += " AND link_status = 'ok'"

    query += " ORDER BY created_at DESC"

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()

    results = []
    exact_ids = set()
    for row in rows:
        bookmark = _row_to_dict(row)
        if search:
            bookmark["match"] = "exact"
        results.append(bookmark)
        exact_ids.add(row["id"])

    # Semantic pass: nearest neighbors of the query embedding, appended after
    # exact matches so precise hits always rank first. Tag browsing is already
    # an exact filter, so vectors only apply to free-text search.
    if search and not tag and not status:
        try:
            query_vector = await embed_query(search)
            if query_vector is not None:
                index = await get_semantic_index(request.app.state)
                hits = await index.search(db, query_vector, exclude_ids=exact_ids)
                if hits:
                    placeholders = ",".join("?" * len(hits))
                    cursor = await db.execute(
                        f"SELECT * FROM bookmarks WHERE id IN ({placeholders})",
                        [bookmark_id for bookmark_id, _ in hits],
                    )
                    by_id = {row["id"]: row for row in await cursor.fetchall()}
                    scored = [
                        (by_id[bookmark_id], score)
                        for bookmark_id, score in hits
                        if bookmark_id in by_id
                    ]
                    for row, score in scored:
                        bookmark = _row_to_dict(row)
                        bookmark["match"] = "semantic"
                        bookmark["score"] = score
                        results.append(bookmark)
        except Exception:
            logger.exception(
                "Semantic search failed for %r; serving exact matches only", search
            )

    return results


@app.put("/api/bookmarks/{bookmark_id}")
async def update_bookmark(request: Request, bookmark_id: int, update: BookmarkUpdate):
    db = request.app.state.db

    row = await db.execute("SELECT * FROM bookmarks WHERE id = ?", (bookmark_id,))
    existing = await row.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    fields = []
    params = []
    if update.url is not None and update.url != existing["url"]:
        dup = await db.execute(
            "SELECT id FROM bookmarks WHERE url = ? AND id != ?",
            (update.url, bookmark_id),
        )
        if await dup.fetchone():
            raise HTTPException(status_code=409, detail="URL already exists")
        fields.append("url = ?")
        params.append(update.url)
        # The URL changed (e.g. adopting a redirect target) — the old
        # link-health verdict no longer applies; clear it for a re-check.
        fields += [
            "link_status = NULL", "link_status_code = NULL",
            "link_final_url = NULL", "link_checked_at = NULL",
            "link_fail_count = 0",
        ]
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

        # Content that feeds the embedding changed — recompute it.
        if any(f in fields for f in ("title = ?", "description = ?", "tags = ?")):
            row = await db.execute(
                "SELECT title, description, tags FROM bookmarks WHERE id = ?",
                (bookmark_id,),
            )
            current = await row.fetchone()
            embedding = await embed_bookmark(
                current["title"], current["description"], current["tags"]
            )
            await db.execute(
                "UPDATE bookmarks SET embedding = ? WHERE id = ?",
                (embedding, bookmark_id),
            )
            await db.commit()
        invalidate_index(app.state)

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
    invalidate_index(app.state)
    logger.info("Deleted bookmark %d", bookmark_id)
    return Response(status_code=204)


@app.get("/api/link-health")
async def link_health(request: Request):
    """Counts backing the sidebar link-health filters, plus the last sweep."""
    db = request.app.state.db
    t = settings.link_check_broken_threshold
    cursor = await db.execute(
        "SELECT "
        " SUM(CASE WHEN link_status = 'broken' AND COALESCE(link_fail_count, 0) >= ?"
        "          THEN 1 ELSE 0 END) AS broken,"
        " SUM(CASE WHEN link_status IN ('uncertain', 'moved')"
        "          OR (link_status = 'broken' AND COALESCE(link_fail_count, 0) < ?)"
        "          THEN 1 ELSE 0 END) AS review,"
        " SUM(CASE WHEN link_status IS NOT NULL THEN 1 ELSE 0 END) AS checked,"
        " COUNT(*) AS total "
        "FROM bookmarks",
        (t, t),
    )
    row = await cursor.fetchone()
    run = await latest_run(db)
    return {
        "broken": row["broken"] or 0,
        "review": row["review"] or 0,
        "checked": row["checked"] or 0,
        "total": row["total"] or 0,
        "last_run": _run_to_dict(run),
    }


@app.post("/api/admin/link-check")
async def start_link_check(request: Request):
    _require_admin(request)
    db = request.app.state.db
    if await active_run(db):
        raise HTTPException(status_code=409, detail="A link check is already running")

    run_id = await create_run(db)
    # Background task on this worker's event loop; progress is polled via GET
    # (which either worker can serve — it reads link_check_runs).
    task = asyncio.create_task(run_link_check(db, run_id))
    request.app.state.link_check_task = task

    def _log_crash(t: asyncio.Task) -> None:
        if not t.cancelled() and t.exception():
            logger.error("Link check task crashed: %r", t.exception())

    task.add_done_callback(_log_crash)
    logger.info("Started link check run %s", run_id)
    return _run_to_dict(await latest_run(db))


@app.get("/api/admin/link-check")
async def link_check_status(request: Request):
    _require_admin(request)
    db = request.app.state.db
    return {
        "run": _run_to_dict(await latest_run(db)),
        "active": await active_run(db) is not None,
    }


async def _search_ids(request: Request, db, search: str) -> set[int]:
    """Ids of bookmarks matching `search`, by the same exact+semantic rules
    as /api/bookmarks (tag filtering is deliberately excluded — see there)."""
    cursor = await db.execute(
        "SELECT id FROM bookmarks WHERE title LIKE ? OR url LIKE ? OR description LIKE ? OR tags LIKE ?",
        [f"%{search}%"] * 4,
    )
    ids = {row["id"] for row in await cursor.fetchall()}

    try:
        query_vector = await embed_query(search)
        if query_vector is not None:
            index = await get_semantic_index(request.app.state)
            hits = await index.search(db, query_vector, exclude_ids=ids)
            ids.update(bookmark_id for bookmark_id, _ in hits)
    except Exception:
        logger.exception("Semantic lookup failed for %r while scoping tags", search)

    return ids


@app.get("/api/tags")
async def get_tags(request: Request, search: str | None = None):
    db = request.app.state.db

    # When a search is active, scope the tag list + counts to the matching
    # bookmarks so the sidebar reflects what's actually on screen, instead
    # of always listing every tag in the library.
    if search:
        ids = await _search_ids(request, db, search)
        rows = []
        if ids:
            placeholders = ",".join("?" * len(ids))
            cursor = await db.execute(
                f"SELECT tags FROM bookmarks WHERE id IN ({placeholders}) AND tags != '' AND tags IS NOT NULL",
                list(ids),
            )
            rows = await cursor.fetchall()
    else:
        cursor = await db.execute("SELECT tags FROM bookmarks WHERE tags != '' AND tags IS NOT NULL")
        rows = await cursor.fetchall()

    counter = Counter()
    for row in rows:
        for tag in row["tags"].split(","):
            tag = tag.strip()
            if tag:
                counter[tag] += 1

    # "total" backs the "All bookmarks" sidebar entry, which clears filters —
    # it always reflects the whole library, not the current search scope.
    total_cursor = await db.execute("SELECT COUNT(*) FROM bookmarks")
    total = (await total_cursor.fetchone())[0]
    return {
        "total": total,
        "tags": [{"tag": tag, "count": count} for tag, count in counter.most_common()],
    }


@app.get("/api/analytics")
async def get_analytics(request: Request):
    db = request.app.state.db

    total_cursor = await db.execute("SELECT COUNT(*) FROM bookmarks")
    total_bookmarks = (await total_cursor.fetchone())[0]

    tags_cursor = await db.execute("SELECT tags FROM bookmarks WHERE tags != '' AND tags IS NOT NULL")
    tag_counter = Counter()
    for row in await tags_cursor.fetchall():
        for tag in row["tags"].split(","):
            tag = tag.strip()
            if tag:
                tag_counter[tag] += 1

    url_cursor = await db.execute("SELECT url FROM bookmarks")
    domain_counter = Counter()
    for row in await url_cursor.fetchall():
        host = urlparse(row["url"]).hostname or ""
        host = host.removeprefix("www.")
        if host:
            domain_counter[host] += 1

    period_cursor = await db.execute(
        "SELECT strftime('%Y-%m', created_at) AS period, COUNT(*) AS n "
        "FROM bookmarks WHERE created_at IS NOT NULL GROUP BY period ORDER BY period"
    )
    counts_by_period = {row["period"]: row["n"] for row in await period_cursor.fetchall()}

    # Zero-fill every month between the first and last bookmark so the
    # timeline reads as a continuous axis, not just the months with activity.
    timeline = []
    if counts_by_period:
        cursor_date = date.fromisoformat(min(counts_by_period) + "-01")
        end_date = date.fromisoformat(max(counts_by_period) + "-01")
        while cursor_date <= end_date:
            period = cursor_date.strftime("%Y-%m")
            timeline.append(
                {
                    "period": period,
                    "label": cursor_date.strftime("%b %Y"),
                    "count": counts_by_period.get(period, 0),
                }
            )
            cursor_date = date(
                cursor_date.year + (cursor_date.month == 12),
                cursor_date.month % 12 + 1,
                1,
            )

    this_month = date.today().strftime("%Y-%m")

    return {
        "total_bookmarks": total_bookmarks,
        "total_tags": len(tag_counter),
        "total_domains": len(domain_counter),
        "added_this_month": counts_by_period.get(this_month, 0),
        "timeline": timeline,
        "top_tags": [{"tag": tag, "count": count} for tag, count in tag_counter.most_common(30)],
        "top_domains": [{"domain": domain, "count": count} for domain, count in domain_counter.most_common(10)],
    }
