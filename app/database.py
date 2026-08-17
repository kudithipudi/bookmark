import aiosqlite
import os

# DB_PATH is the standard env var name; DATABASE_PATH is kept as a legacy
# fallback for existing deployments/configs.
DATABASE_PATH = os.getenv("DB_PATH") or os.getenv("DATABASE_PATH") or "data/bookmarks.db"

SQL_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    title TEXT,
    description TEXT,
    favicon TEXT,
    tags TEXT DEFAULT '',
    is_favorite BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

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
    path = db_path or DATABASE_PATH
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
    await db.execute(SQL_CREATE_RATE_LIMIT_TABLE)
    await db.execute(SQL_CREATE_RATE_LIMIT_INDEX)
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
