import logging
import os

import aiosqlite

from app.config import settings

logger = logging.getLogger(__name__)

SQL_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    title TEXT,
    description TEXT,
    favicon TEXT,
    tags TEXT DEFAULT '',
    is_favorite BOOLEAN DEFAULT 0,
    embedding BLOB,
    link_status TEXT,
    link_status_code INTEGER,
    link_final_url TEXT,
    link_checked_at TIMESTAMP,
    link_last_ok_at TIMESTAMP,
    link_fail_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

# One row per bulk link-check run: progress counters the frontend polls
# while a sweep is in flight, plus a history of past sweeps. Kept in the DB
# (not worker memory) so either gunicorn worker can serve the status.
SQL_CREATE_LINK_CHECK_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS link_check_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    finished_at TEXT,
    total INTEGER NOT NULL DEFAULT 0,
    checked INTEGER NOT NULL DEFAULT 0,
    ok INTEGER NOT NULL DEFAULT 0,
    broken INTEGER NOT NULL DEFAULT 0,
    moved INTEGER NOT NULL DEFAULT 0,
    uncertain INTEGER NOT NULL DEFAULT 0,
    error TEXT
)
"""

# Columns added to `bookmarks` after its first release. SQLite has no
# "ADD COLUMN IF NOT EXISTS", so init_db() diffs this against the live
# schema and ALTERs in whatever's missing.
_BOOKMARK_MIGRATIONS = {
    "embedding": "ALTER TABLE bookmarks ADD COLUMN embedding BLOB",
    "link_status": "ALTER TABLE bookmarks ADD COLUMN link_status TEXT",
    "link_status_code": "ALTER TABLE bookmarks ADD COLUMN link_status_code INTEGER",
    "link_final_url": "ALTER TABLE bookmarks ADD COLUMN link_final_url TEXT",
    "link_checked_at": "ALTER TABLE bookmarks ADD COLUMN link_checked_at TIMESTAMP",
    "link_last_ok_at": "ALTER TABLE bookmarks ADD COLUMN link_last_ok_at TIMESTAMP",
    "link_fail_count": "ALTER TABLE bookmarks ADD COLUMN link_fail_count INTEGER DEFAULT 0",
}

# Sliding-window log for per-IP rate limiting: one row per hit, not fixed
# buckets. A plain table (not an in-process counter) so the limit is
# enforced consistently across gunicorn workers, which don't share memory.
SQL_CREATE_RATE_LIMIT_TABLE = """
CREATE TABLE IF NOT EXISTS rate_limit_hits (
    ip TEXT NOT NULL,
    route TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
)
"""

SQL_CREATE_RATE_LIMIT_INDEX = """
CREATE INDEX IF NOT EXISTS idx_rate_limit_hits_route_ip_time
    ON rate_limit_hits (route, ip, created_at)
"""


async def get_db(db_path: str | None = None) -> aiosqlite.Connection:
    path = db_path or settings.db_path
    dirname = os.path.dirname(path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db(db_path: str | None = None):
    db = await get_db(db_path)
    await db.execute(SQL_CREATE_TABLE)
    # Bring pre-existing databases up to the current bookmarks schema.
    cursor = await db.execute("PRAGMA table_info(bookmarks)")
    columns = {row[1] for row in await cursor.fetchall()}
    for column, ddl in _BOOKMARK_MIGRATIONS.items():
        if column not in columns:
            logger.info("Adding bookmarks.%s column (migration)", column)
            await db.execute(ddl)
    await db.execute(SQL_CREATE_RATE_LIMIT_TABLE)
    await db.execute(SQL_CREATE_RATE_LIMIT_INDEX)
    await db.execute(SQL_CREATE_LINK_CHECK_RUNS_TABLE)
    await db.commit()
    await db.close()


async def check_and_record_rate_limit(
    conn: aiosqlite.Connection,
    *,
    ip: str,
    route: str,
    limit: int,
    window_seconds: int,
) -> bool:
    """Record a hit for (ip, route) and return whether it's within `limit`
    hits in the trailing `window_seconds`. Also prunes hits for this route
    older than the window, so the table doesn't grow unbounded."""
    offset = f"-{window_seconds} seconds"
    await conn.execute(
        "DELETE FROM rate_limit_hits WHERE route = ?"
        " AND created_at < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)",
        (route, offset),
    )
    cur = await conn.execute(
        "SELECT COUNT(*) FROM rate_limit_hits WHERE route = ? AND ip = ?"
        " AND created_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)",
        (route, ip, offset),
    )
    row = await cur.fetchone()
    if row[0] >= limit:
        await conn.commit()
        return False
    await conn.execute(
        "INSERT INTO rate_limit_hits (ip, route) VALUES (?, ?)", (ip, route)
    )
    await conn.commit()
    return True
