import logging
import os
import re

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

# Backs the `ORDER BY created_at DESC` every bookmarks list read does.
SQL_CREATE_BOOKMARKS_CREATED_AT_INDEX = """
CREATE INDEX IF NOT EXISTS idx_bookmarks_created_at
    ON bookmarks(created_at DESC)
"""

# External-content FTS5 mirror of the bookmarks free-text columns, kept in
# sync by the triggers below. Replaces the 4x `LIKE '%term%'` table scans in
# the search path. content='bookmarks' means the index stores only the
# tokenized terms; the row data is read back from `bookmarks` by rowid.
SQL_CREATE_FTS_TABLE = """
CREATE VIRTUAL TABLE IF NOT EXISTS bookmarks_fts USING fts5(
    title, url, description, tags,
    content='bookmarks', content_rowid='id'
)
"""

# The documented external-content sync triggers. Deletes/updates push a
# 'delete' sentinel row (old values) so FTS can remove the stale terms.
SQL_CREATE_FTS_INSERT_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS bookmarks_fts_ai AFTER INSERT ON bookmarks BEGIN
    INSERT INTO bookmarks_fts(rowid, title, url, description, tags)
    VALUES (new.id, new.title, new.url, new.description, new.tags);
END
"""

SQL_CREATE_FTS_DELETE_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS bookmarks_fts_ad AFTER DELETE ON bookmarks BEGIN
    INSERT INTO bookmarks_fts(bookmarks_fts, rowid, title, url, description, tags)
    VALUES ('delete', old.id, old.title, old.url, old.description, old.tags);
END
"""

SQL_CREATE_FTS_UPDATE_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS bookmarks_fts_au AFTER UPDATE ON bookmarks BEGIN
    INSERT INTO bookmarks_fts(bookmarks_fts, rowid, title, url, description, tags)
    VALUES ('delete', old.id, old.title, old.url, old.description, old.tags);
    INSERT INTO bookmarks_fts(rowid, title, url, description, tags)
    VALUES (new.id, new.title, new.url, new.description, new.tags);
END
"""

SQL_CREATE_FTS_TRIGGERS = (
    SQL_CREATE_FTS_INSERT_TRIGGER,
    SQL_CREATE_FTS_DELETE_TRIGGER,
    SQL_CREATE_FTS_UPDATE_TRIGGER,
)

# Characters FTS5 reads as query syntax (quotes, prefix star, grouping,
# column filters, NOT, NEAR-ish). Stripped from user tokens before we build
# a MATCH string so a raw query can never be a malformed FTS expression.
_FTS_SPECIAL = re.compile(r'["*():^{}\[\]~+\\-]')


def fts_match_query(raw: str) -> str | None:
    """Turn a raw user search string into a safe FTS5 MATCH expression.

    Each whitespace-separated token is stripped of FTS special characters,
    wrapped in double quotes, and given a trailing ``*`` (prefix match);
    tokens are joined with spaces (implicit AND). Returns ``None`` if nothing
    usable remains, so callers can fall back to the old LIKE query.
    """
    tokens = []
    for token in raw.split():
        cleaned = _FTS_SPECIAL.sub("", token).strip()
        if cleaned:
            tokens.append(f'"{cleaned}"*')
    if not tokens:
        return None
    return " ".join(tokens)


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
    await db.execute(SQL_CREATE_BOOKMARKS_CREATED_AT_INDEX)
    await db.execute(SQL_CREATE_FTS_TABLE)
    for trigger_ddl in SQL_CREATE_FTS_TRIGGERS:
        await db.execute(trigger_ddl)
    await db.commit()

    # First deploy against an existing library: the triggers only cover rows
    # written from here on, so seed the FTS index from what's already there.
    # (Counting `bookmarks_fts` itself just reads the content table, so check
    # the docsize shadow table — one row per actually-indexed document.)
    cursor = await db.execute("SELECT COUNT(*) FROM bookmarks")
    bookmarks_count = (await cursor.fetchone())[0]
    cursor = await db.execute("SELECT COUNT(*) FROM bookmarks_fts_docsize")
    fts_count = (await cursor.fetchone())[0]
    if bookmarks_count and not fts_count:
        logger.info("Rebuilding bookmarks_fts index for %d existing rows", bookmarks_count)
        await db.execute("INSERT INTO bookmarks_fts(bookmarks_fts) VALUES('rebuild')")
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
