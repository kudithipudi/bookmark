"""Bulk link checker: probe every bookmark's URL and record whether it still
resolves, so dead links can be surfaced (and reviewed) instead of silently
rotting. Deliberately conservative — a URL must fail several consecutive
sweeps before it's called "broken", and bot walls / rate limits / transient
5xx are recorded as "uncertain", never "broken".
"""

import asyncio
import logging
import socket
from urllib.parse import urlparse

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_NOW_SQL = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
_NOW_OFFSET_SQL = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)"

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36 (BookmarkLinkChecker; +https://lab.kudithipudi.org/bookmark/)"
)

# The server answered, but the answer doesn't prove the link is dead:
# auth walls (401), bot walls (403), method quirks (405), rate limits (429),
# and transient server errors (5xx).
_UNCERTAIN_CODES = {401, 403, 405, 429, 500, 502, 503, 504}

_BUCKETS = ("ok", "moved", "broken", "uncertain")


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").removeprefix("www.").lower()


def _is_dns_failure(exc: BaseException) -> bool:
    """True if a name-resolution error is anywhere in the exception chain —
    an unregistered / vanished domain, the strongest 'this is dead' signal."""
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, socket.gaierror):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def classify(status_code: int | None, original_url: str, final_url: str | None) -> str:
    """Map an HTTP result to one of _BUCKETS."""
    if status_code is None:
        return "uncertain"
    if 200 <= status_code < 300:
        if final_url and _host(final_url) and _host(final_url) != _host(original_url):
            return "moved"
        return "ok"
    if status_code in (404, 410):
        return "broken"
    if status_code in _UNCERTAIN_CODES:
        return "uncertain"
    if 400 <= status_code < 500:
        return "broken"
    return "uncertain"


async def check_url(client: httpx.AsyncClient, url: str) -> tuple[str, int | None, str | None]:
    """Probe one URL. Returns (bucket, status_code_or_None, final_url_or_None)."""
    if not url.startswith(("http://", "https://")):
        return "uncertain", None, None

    try:
        resp: httpx.Response | None = None
        try:
            resp = await client.head(url)
        except httpx.HTTPError:
            resp = None

        # HEAD is widely misimplemented — fall back to a ranged GET when it's
        # missing, refused, or itself inconclusive. Range keeps the download
        # tiny for servers that honour it (a bookmarked video/PDF otherwise).
        if resp is None or resp.status_code in (403, 404, 405, 501) or resp.status_code >= 500:
            resp = await client.get(url, headers={"Range": "bytes=0-2047"})

        code = resp.status_code
        final_url = str(resp.url)
        return classify(code, url, final_url), code, final_url

    except httpx.TimeoutException:
        return "uncertain", None, None
    except httpx.HTTPError as exc:
        if _is_dns_failure(exc):
            return "broken", None, None
        # Connection refused / host unreachable is a strong dead signal, but
        # can be a transient outage — let the consecutive-failure threshold
        # decide whether it's really "broken".
        bucket = "broken" if isinstance(exc, httpx.ConnectError) else "uncertain"
        return bucket, None, None


async def _record_result(
    db, bookmark_id: int, bucket: str, code: int | None, final_url: str | None
) -> None:
    if bucket in ("ok", "moved"):
        await db.execute(
            f"UPDATE bookmarks SET link_status = ?, link_status_code = ?, "
            f"link_final_url = ?, link_checked_at = {_NOW_SQL}, "
            f"link_last_ok_at = {_NOW_SQL}, link_fail_count = 0 WHERE id = ?",
            (bucket, code, final_url if bucket == "moved" else None, bookmark_id),
        )
    else:
        await db.execute(
            f"UPDATE bookmarks SET link_status = ?, link_status_code = ?, "
            f"link_checked_at = {_NOW_SQL}, "
            f"link_fail_count = COALESCE(link_fail_count, 0) + 1 WHERE id = ?",
            (bucket, code, bookmark_id),
        )


async def create_run(db) -> int:
    """Insert a fresh link_check_runs row and return its id."""
    cur = await db.execute("SELECT COUNT(*) AS n FROM bookmarks")
    total = (await cur.fetchone())["n"]
    cur = await db.execute("INSERT INTO link_check_runs (total) VALUES (?)", (total,))
    await db.commit()
    return cur.lastrowid


async def latest_run(db):
    cur = await db.execute("SELECT * FROM link_check_runs ORDER BY id DESC LIMIT 1")
    return await cur.fetchone()


async def active_run(db):
    """The most recent run that's still genuinely in flight. A run whose row
    never got a finished_at (worker restarted mid-sweep) stops counting as
    active once it's older than link_check_stale_after_seconds. Timestamps
    are compared as strings (same trick as the rate limiter) to avoid
    SQLite's inconsistent parsing of the trailing 'Z'."""
    offset = f"-{settings.link_check_stale_after_seconds} seconds"
    cur = await db.execute(
        "SELECT * FROM link_check_runs WHERE finished_at IS NULL "
        f"AND started_at >= {_NOW_OFFSET_SQL} ORDER BY id DESC LIMIT 1",
        (offset,),
    )
    return await cur.fetchone()


async def run_link_check(db, run_id: int) -> None:
    """Sweep every bookmark URL, updating each row and the run's counters.
    Runs as a background task; the frontend polls link_check_runs for
    progress. Never raises — failures are recorded on the run row."""
    counts = {b: 0 for b in _BUCKETS}
    try:
        cur = await db.execute("SELECT id, url FROM bookmarks ORDER BY id")
        bookmarks = [(r["id"], r["url"]) for r in await cur.fetchall()]
        total = len(bookmarks)

        sem = asyncio.Semaphore(settings.link_check_concurrency)
        timeout = httpx.Timeout(settings.link_check_timeout_seconds)
        limits = httpx.Limits(max_connections=settings.link_check_concurrency + 5)

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            limits=limits,
            headers={"User-Agent": _USER_AGENT},
            max_redirects=10,
        ) as client:

            async def worker(bookmark_id: int, url: str) -> None:
                async with sem:
                    bucket, code, final_url = await check_url(client, url)
                # aiosqlite serialises writes on its single connection, so do
                # them outside the semaphore — a slow site shouldn't hold a slot.
                await _record_result(db, bookmark_id, bucket, code, final_url)
                counts[bucket] += 1
                done = sum(counts.values())
                if done % 10 == 0 or done == total:
                    await db.execute(
                        "UPDATE link_check_runs SET checked = ?, ok = ?, broken = ?, "
                        "moved = ?, uncertain = ? WHERE id = ?",
                        (done, counts["ok"], counts["broken"], counts["moved"],
                         counts["uncertain"], run_id),
                    )
                    await db.commit()

            await asyncio.gather(*(worker(bid, url) for bid, url in bookmarks))

        await db.execute(
            f"UPDATE link_check_runs SET finished_at = {_NOW_SQL}, checked = ?, "
            "ok = ?, broken = ?, moved = ?, uncertain = ? WHERE id = ?",
            (sum(counts.values()), counts["ok"], counts["broken"], counts["moved"],
             counts["uncertain"], run_id),
        )
        await db.commit()
        logger.info("Link check run %s complete: %s", run_id, counts)
    except Exception as exc:  # noqa: BLE001 — must not leave the run "active" forever
        logger.exception("Link check run %s failed", run_id)
        try:
            await db.execute(
                f"UPDATE link_check_runs SET finished_at = {_NOW_SQL}, error = ? WHERE id = ?",
                (str(exc)[:500], run_id),
            )
            await db.commit()
        except Exception:
            logger.exception("Could not record link check failure for run %s", run_id)
