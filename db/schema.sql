-- Canonical schema for the bookmark app's SQLite database.
-- Applied idempotently on startup via app/database.py (CREATE TABLE IF NOT EXISTS).
-- Keep in sync with app/database.py:SQL_CREATE_TABLE / SQL_CREATE_RATE_LIMIT_TABLE.

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

-- Sliding-window log for per-IP rate limiting on abusable routes.
CREATE TABLE IF NOT EXISTS rate_limit_hits (
    ip TEXT NOT NULL,
    route TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_rate_limit_hits_route_ip_time ON rate_limit_hits (route, ip, created_at);
