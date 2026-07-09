-- Canonical schema for the bookmark app's SQLite database.
-- Applied idempotently on startup via app/database.py (CREATE TABLE IF NOT EXISTS).
-- Keep in sync with app/database.py:SQL_CREATE_TABLE.

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
);
