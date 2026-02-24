# Bookmarks

A simple, self-hosted bookmarking web app. Save URLs, auto-fetch metadata, get AI-generated tags, and organize everything with search and tag filtering.

Built with FastAPI, Alpine.js, SQLite, and OpenRouter for AI tagging.

## Features

- **Save bookmarks** — paste a URL; title, description, and favicon are scraped automatically
- **AI auto-tagging** — OpenRouter generates 3-5 tags per bookmark on save
- **Search** — full-text search across title, URL, description, and tags
- **Filter by tag** — click any tag to filter; tag sidebar with counts
- **Edit / Delete** — inline editing of title, description, and tags
- **Responsive** — card grid adapts from 1 to 3 columns

## Architecture

```
/var/www/bookmark/
├── app/
│   ├── main.py          # FastAPI routes
│   ├── database.py      # SQLite setup (aiosqlite, WAL mode)
│   ├── models.py        # Pydantic models
│   ├── scraper.py       # URL metadata fetcher (httpx + BeautifulSoup)
│   └── ai.py            # OpenRouter integration for auto-tagging
├── static/
│   ├── app.js           # Alpine.js frontend logic
│   └── style.css        # Minimal custom styles
├── templates/
│   └── index.html       # Single-page Jinja2 template
├── tests/               # pytest test suite
├── seed.py              # Seeds 30 sample bookmarks
├── gunicorn.conf.py     # Gunicorn config (unix socket, uvicorn workers)
└── nginx.conf           # Nginx reverse proxy config
```

## Quick Start

### Prerequisites

- Python 3.12+
- A virtual environment at `./venv`

### Install

```bash
cd /var/www/bookmark
source venv/bin/activate
pip install -r requirements.txt
```

### Configure

Create a `.env` file:

```bash
# Required for AI auto-tagging (optional — tags will be empty without it)
OPENROUTER_API_KEY=your-key-here

# SQLite database path (default: bookmarks.db)
# DATABASE_PATH=/var/www/bookmark/bookmarks.db
```

### Seed sample data (optional)

```bash
python seed.py
```

Populates the database with 30 bookmarks across tech, finance, tools, learning, and travel categories.

### Run (development)

```bash
uvicorn app.main:app --reload
```

Open `http://localhost:8000`.

### Run (production)

The app runs behind Gunicorn (unix socket) + Nginx:

```bash
# Start via systemd
sudo systemctl start bookmark
sudo systemctl enable bookmark

# Check status
sudo systemctl status bookmark

# View logs
sudo journalctl -u bookmark -f
```

Gunicorn binds to `unix:/var/www/bookmark/gunicorn.sock` with 4 uvicorn workers. Nginx proxies to the socket and serves static files directly.

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Serves the frontend |
| `GET` | `/api/bookmarks` | List bookmarks. Query params: `search`, `tag` |
| `POST` | `/api/bookmarks` | Create bookmark. Body: `{"url": "..."}` |
| `PUT` | `/api/bookmarks/{id}` | Update bookmark. Body: `{"title", "description", "tags"}` |
| `DELETE` | `/api/bookmarks/{id}` | Delete bookmark |
| `GET` | `/api/tags` | List all tags with counts |

## Database

SQLite with WAL mode. Single table:

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER | Primary key, autoincrement |
| `url` | TEXT | Unique, not null |
| `title` | TEXT | Auto-scraped from page |
| `description` | TEXT | Auto-scraped from meta tag |
| `favicon` | TEXT | Auto-scraped favicon URL |
| `tags` | TEXT | Comma-separated, AI-generated |
| `created_at` | TIMESTAMP | Auto-set |
| `updated_at` | TIMESTAMP | Auto-set on update |

## Tests

```bash
python -m pytest tests/ -v
```

16 tests across 4 files:
- `test_api.py` — CRUD, search, tag filtering, duplicate detection
- `test_scraper.py` — metadata fetching (mocked HTTP)
- `test_ai.py` — OpenRouter tagging (mocked)
- `test_integration.py` — end-to-end workflows

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | FastAPI, Python 3.12 |
| Database | SQLite (aiosqlite) |
| Frontend | Alpine.js, Tailwind CSS (CDN) |
| Scraping | httpx, BeautifulSoup4 |
| AI Tagging | OpenRouter (google/gemini-2.0-flash-001) |
| App Server | Gunicorn + Uvicorn workers |
| Reverse Proxy | Nginx |
| Process Manager | systemd |
