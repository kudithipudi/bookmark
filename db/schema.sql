-- Canonical schema for the bookmark app's SQLite database.
-- Applied idempotently on startup via app/db.py (CREATE TABLE IF NOT EXISTS
-- plus PRAGMA-guarded ALTERs for columns added after the first release).
-- Keep in sync with app/db.py:SQL_CREATE_TABLE / SQL_CREATE_RATE_LIMIT_TABLE /
-- SQL_CREATE_LINK_CHECK_RUNS_TABLE / _BOOKMARK_MIGRATIONS.

CREATE TABLE IF NOT EXISTS bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    title TEXT,
    description TEXT,
    favicon TEXT,
    tags TEXT DEFAULT '',
    is_favorite BOOLEAN DEFAULT 0,
    embedding BLOB,
    -- Bulk link checker (app/services/linkcheck.py): last verdict per URL.
    -- link_status ∈ ok | moved | broken | uncertain (NULL = never checked).
    link_status TEXT,
    link_status_code INTEGER,
    link_final_url TEXT,               -- redirect target when link_status = 'moved'
    link_checked_at TIMESTAMP,
    link_last_ok_at TIMESTAMP,
    link_fail_count INTEGER DEFAULT 0, -- consecutive non-ok sweeps
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

-- One row per bulk link-check run: live progress counters (polled by the
-- frontend) plus a history of past sweeps.
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
);
