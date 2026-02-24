import aiosqlite
import os

DATABASE_PATH = os.getenv("DATABASE_PATH", "bookmarks.db")

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
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    return db


async def init_db(db_path: str | None = None):
    db = await get_db(db_path)
    await db.execute(SQL_CREATE_TABLE)
    await db.commit()
    await db.close()
