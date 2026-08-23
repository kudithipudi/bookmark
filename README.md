# Bookmarks

## What it is

A simple, self-hosted bookmarking web app. Save URLs, auto-fetch metadata
(title, description, favicon), get AI-generated tags via OpenRouter, and
organize everything with search and tag filtering. Search is hybrid: exact
keyword matches rank first, then semantic nearest-neighbor matches found by
meaning (local embeddings — "app for organizing my thoughts" finds Obsidian).
Semantic-only hits are badged `Related` in the UI. Served at
`https://lab.kudithipudi.org/bookmark/`.

## Stack

| Component | Technology |
|-----------|-----------|
| Backend | FastAPI, Python 3.12 |
| Database | SQLite (aiosqlite, WAL mode) at `data/bookmarks.db` |
| Frontend | Jinja2, Alpine.js 3.14.8 (pinned CDN + SRI), Tailwind CSS (built with standalone CLI) |
| Scraping | httpx, BeautifulSoup4 |
| AI Tagging | OpenRouter (model configurable, default `google/gemini-2.5-flash`) |
| Semantic Search | fastembed (local ONNX, `BAAI/bge-small-en-v1.5`, 384-dim), brute-force cosine over an in-process vector cache |
| App Server | gunicorn + uvicorn workers, unix socket `bookmark.sock` |
| Reverse Proxy | nginx (subpath `/bookmark/`) |
| Process Manager | systemd (`bookmark.service`) |

Layout:

```
/var/www/bookmark/
├── app/
│   ├── main.py            # FastAPI app + routes
│   ├── config.py          # pydantic-settings Settings (reads .env)
│   ├── db.py              # SQLite access (aiosqlite, WAL)
│   ├── models.py          # Pydantic models
│   ├── scraper.py         # URL metadata fetcher
│   ├── services/
│   │   ├── llm.py            # OpenRouter auto-tagging client
│   │   ├── embeddings.py     # local fastembed embedding generation
│   │   └── semantic_index.py # in-memory vector cache + cosine NN search
│   ├── templates/index.html  # single-page UI
│   ├── static/            # app.js, style.css, css/app.css (built Tailwind)
│   └── logs/              # access.log + app.log (gitignored; .gitkeep committed)
├── data/                  # SQLite db (gitignored, www-data writable)
├── db/schema.sql          # canonical schema
├── tests/                 # pytest suite
├── gunicorn.conf.py
├── tailwind.config.js
├── .env.example           # copy to .env and fill in
└── requirements.txt
```

## Run locally

```bash
cd /var/www/bookmark
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload   # http://localhost:8000
```

Optional: seed 30 sample bookmarks with `python seed.py`.

### Semantic search

Bookmarks are embedded at create/update time (title + description + tags,
local ONNX model — no API cost) into a nullable `embedding` BLOB column.
Search embeds the query, does brute-force cosine against all embeddings
in memory (sub-millisecond at personal-library scale), and appends the
nearest neighbors above `SEMANTIC_SCORE_THRESHOLD` after exact matches.
Responses include `"match": "exact" | "semantic"` (+ `score` for semantic).

For an existing database, backfill embeddings once after deploying:

```bash
venv/bin/python backfill_embeddings.py          # only rows missing one
venv/bin/python backfill_embeddings.py --force  # recompute all (after changing EMBEDDING_MODEL)
```

If the model can't load (e.g., first-run download blocked), semantic
features silently degrade to exact-match-only until restart.

### Tests

```bash
venv/bin/python -m pytest
```

### Rebuilding the Tailwind CSS

The UI uses a committed CSS file built by the Tailwind standalone CLI (no
Node/CDN at runtime). After changing templates, rebuild:

```bash
# One-time: download the v3.4.17 standalone CLI
curl -sLo /usr/local/bin/tailwindcss \
  https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/tailwindcss-linux-x64
chmod +x /usr/local/bin/tailwindcss

cd /var/www/bookmark
tailwindcss -c tailwind.config.js -i app/static/css/input.css \
  -o app/static/css/app.css --minify
```

## Deploy

```bash
sudo systemctl restart bookmark
systemctl is-active bookmark
curl -s -o /dev/null -w '%{http_code}' https://lab.kudithipudi.org/bookmark/  # 200
curl -s https://lab.kudithipudi.org/bookmark/health                           # {"status":"ok"}
```

Note: the app does **not** set FastAPI's `root_path`. nginx's `/bookmark/`
location strips the prefix (`rewrite ^/bookmark(/.*)$ $1 break;`) before
proxying, and templates prefix outgoing links with `{{ prefix }}` (the Jinja
global bound to `ROOT_PATH`), so the app sees clean, unprefixed paths.
Setting `root_path` here would double-account the prefix inside Starlette's
route resolution and break the `/static` mount.

## Logs

Logs live in local files under `app/logs/`, not journald:

| File | Contents |
|------|----------|
| `app/logs/access.log` | gunicorn access log — one line per HTTP request |
| `app/logs/app.log` | gunicorn boot/error log plus everything the app emits via `logging` |

Verbosity is controlled by `LOG_LEVEL` in `.env` (default `info`; set `debug`
to flip just this app to verbose). Rotation is handled by the host-level
logrotate policy (`/etc/logrotate.d/lab-apps`, weekly, 8 rotations,
compress) — no per-app rotation config.

## Env vars

Set in `/var/www/bookmark/.env` (chmod 600, never committed); see
`.env.example` for the canonical list:

| Variable | Default | Description |
|----------|---------|-------------|
| `ROOT_PATH` | (blank) | URL prefix used in templates (`{{ prefix }}`); nginx strips it before proxying |
| `OPENROUTER_API_KEY` | (unset) | OpenRouter key for AI auto-tagging; tags are empty without it |
| `OPENROUTER_MODEL` | `google/gemini-2.5-flash` | OpenRouter model slug for tagging |
| `LLM_TIMEOUT_SECONDS` | `15.0` | Timeout for OpenRouter calls |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | fastembed model for semantic search |
| `SEMANTIC_SCORE_THRESHOLD` | `0.55` | Minimum cosine similarity to include a semantic match |
| `SEMANTIC_SEARCH_LIMIT` | `12` | Max semantic matches per search |
| `DELETE_PASSWORD` | (unset) | If set, deletes require `X-Delete-Password` header |
| `DB_PATH` | `data/bookmarks.db` | SQLite database path (legacy alias: `DATABASE_PATH`) |
| `LOG_LEVEL` | `info` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `RATE_LIMIT_PER_MINUTE` | `20` | Max bookmark creations per IP per window |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Rate-limit window length in seconds |

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Serves the frontend |
| `GET` | `/health` | Health check — `{"status": "ok"}`, no auth/DB |
| `GET` | `/api/bookmarks` | List bookmarks. Query params: `search` (hybrid exact+semantic), `tag` (exact) |
| `POST` | `/api/bookmarks` | Create bookmark. Body: `{"url": "..."}` |
| `PUT` | `/api/bookmarks/{id}` | Update bookmark. Body: `{"title", "description", "tags"}` |
| `DELETE` | `/api/bookmarks/{id}` | Delete bookmark (requires `X-Delete-Password` if configured) |
| `GET` | `/api/tags` | List all tags with counts |
