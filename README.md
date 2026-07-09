# Bookmarks

## What it is

A simple, self-hosted bookmarking web app. Save URLs, auto-fetch metadata
(title, description, favicon), get AI-generated tags via OpenRouter, and
organize everything with search and tag filtering. Served at
`https://lab.kudithipudi.org/bookmark/`.

## Stack

| Component | Technology |
|-----------|-----------|
| Backend | FastAPI, Python 3.12 |
| Database | SQLite (aiosqlite, WAL mode) at `data/bookmarks.db` |
| Frontend | Jinja2, Alpine.js 3.14.8 (pinned CDN + SRI), Tailwind CSS (built with standalone CLI) |
| Scraping | httpx, BeautifulSoup4 |
| AI Tagging | OpenRouter (model configurable, default `google/gemini-2.5-flash`) |
| App Server | gunicorn + uvicorn workers, unix socket `bookmark.sock` |
| Reverse Proxy | nginx (subpath `/bookmark/`) |
| Process Manager | systemd (`bookmark.service`) |

Layout:

```
/var/www/bookmark/
├── app/
│   ├── main.py            # FastAPI app + routes
│   ├── database.py        # SQLite access (aiosqlite, WAL)
│   ├── models.py          # Pydantic models
│   ├── scraper.py         # URL metadata fetcher
│   ├── ai.py              # OpenRouter auto-tagging
│   ├── logging_config.py  # stdout logging (journald captures it)
│   └── static/            # app.js, style.css, css/app.css (built Tailwind)
├── templates/index.html   # single-page UI
├── data/                  # SQLite db (gitignored, www-data writable)
├── db/schema.sql          # canonical schema
├── tests/                 # pytest suite
├── gunicorn.conf.py
├── tailwind.config.js
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
```

Logs go to stdout and are captured by journald: `journalctl -u bookmark -f`.

## Env vars

Set in `/var/www/bookmark/.env` (chmod 600, never committed):

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | (unset) | OpenRouter key for AI auto-tagging; tags are empty without it |
| `OPENROUTER_MODEL` | `google/gemini-2.5-flash` | OpenRouter model slug for tagging |
| `DELETE_PASSWORD` | (unset) | If set, deletes require `X-Delete-Password` header |
| `DB_PATH` | `data/bookmarks.db` | SQLite database path (legacy alias: `DATABASE_PATH`) |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

Note: the app does **not** set FastAPI's `root_path`. nginx's `/bookmark/`
location strips the prefix (`rewrite ^/bookmark(/.*)$ $1 break;`) before
proxying, and templates use relative asset URLs (`static/...`), so the app
sees clean, unprefixed paths. Setting `root_path` here would double-account
the prefix inside Starlette's route resolution and break the `/static`
mount — confirmed while implementing this: it 404s every static asset.

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Serves the frontend |
| `GET` | `/api/bookmarks` | List bookmarks. Query params: `search`, `tag` |
| `POST` | `/api/bookmarks` | Create bookmark. Body: `{"url": "..."}` |
| `PUT` | `/api/bookmarks/{id}` | Update bookmark. Body: `{"title", "description", "tags"}` |
| `DELETE` | `/api/bookmarks/{id}` | Delete bookmark (requires `X-Delete-Password` if configured) |
| `GET` | `/api/tags` | List all tags with counts |
