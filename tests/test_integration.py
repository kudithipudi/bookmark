import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from app.config import settings


async def test_add_bookmark_with_scraping_and_tagging(client, db):
    html = """
    <html><head>
        <title>Integration Test Page</title>
        <meta name="description" content="A test page for integration">
        <link rel="icon" href="/favicon.ico">
    </head><body></body></html>
    """

    mock_http_response = AsyncMock()
    mock_http_response.status_code = 200
    mock_http_response.text = html
    mock_http_response.url = httpx.URL("https://integration-test.com")

    mock_ai_response = MagicMock()
    mock_ai_response.status_code = 200
    mock_ai_response.json.return_value = {
        "choices": [{"message": {"content": "testing, integration, web"}}]
    }

    async def mock_fetch_metadata(url):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        return {
            "title": soup.find("title").string.strip(),
            "description": soup.find("meta", attrs={"name": "description"})["content"],
            "favicon": "https://integration-test.com/favicon.ico",
        }

    async def mock_generate_tags(url, title, desc):
        return ["testing", "integration", "web"]

    with patch("app.main.fetch_metadata", side_effect=mock_fetch_metadata), \
         patch("app.main.generate_tags", side_effect=mock_generate_tags):
        resp = await client.post("/api/bookmarks", json={"url": "https://integration-test.com"})

    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Integration Test Page"
    assert data["description"] == "A test page for integration"
    assert "testing" in data["tags"]
    assert "integration" in data["tags"]


async def test_create_bookmark_rate_limited(client, db):
    async def mock_fetch_metadata(url):
        return {"title": None, "description": None, "favicon": None}

    async def mock_generate_tags(url, title, desc):
        return []

    with patch("app.main.fetch_metadata", side_effect=mock_fetch_metadata), \
         patch("app.main.generate_tags", side_effect=mock_generate_tags), \
         patch.object(settings, "rate_limit_per_minute", 2), \
         patch.object(settings, "rate_limit_window_seconds", 60):
        r1 = await client.post("/api/bookmarks", json={"url": "https://rl-1.com"})
        r2 = await client.post("/api/bookmarks", json={"url": "https://rl-2.com"})
        r3 = await client.post("/api/bookmarks", json={"url": "https://rl-3.com"})

    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r3.status_code == 429
    assert "Too many requests" in r3.json()["detail"]


async def test_search_and_filter_workflow(client, db):
    await db.execute(
        "INSERT INTO bookmarks (url, title, tags) VALUES (?, ?, ?)",
        ("https://python.org", "Python Official", "python,programming"),
    )
    await db.execute(
        "INSERT INTO bookmarks (url, title, tags) VALUES (?, ?, ?)",
        ("https://rust-lang.org", "Rust Language", "rust,programming"),
    )
    await db.execute(
        "INSERT INTO bookmarks (url, title, tags) VALUES (?, ?, ?)",
        ("https://cooking.com", "Cooking Guide", "cooking,food"),
    )
    await db.commit()

    # Search by title
    resp = await client.get("/api/bookmarks", params={"search": "python"})
    assert len(resp.json()) == 1

    # Filter by tag
    resp = await client.get("/api/bookmarks", params={"tag": "programming"})
    assert len(resp.json()) == 2

    # Get all tags
    resp = await client.get("/api/tags")
    tags = {t["tag"]: t["count"] for t in resp.json()}
    assert tags["programming"] == 2
    assert tags["cooking"] == 1


