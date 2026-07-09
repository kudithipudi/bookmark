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
    await db.commit()
    await db.close()
