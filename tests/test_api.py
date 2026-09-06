import pytest
from unittest.mock import patch
import numpy as np

from app.config import settings
from app.services.semantic_index import EMBEDDING_DIM


async def test_index_page(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "Bookmarks" in resp.text


async def test_update_bookmark_not_found(client):
    resp = await client.put("/api/bookmarks/99999", json={"title": "x"})
    assert resp.status_code == 404


async def test_delete_bookmark_not_found(client):
    resp = await client.delete("/api/bookmarks/99999")
    assert resp.status_code == 404


async def test_create_bookmark(client, db):
    resp = await client.post("/api/bookmarks", json={"url": "https://example.com"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["url"] == "https://example.com"
    assert data["id"] is not None

    row = await db.execute("SELECT * FROM bookmarks WHERE id = ?", (data["id"],))
    bookmark = await row.fetchone()
    assert bookmark is not None
    assert bookmark["url"] == "https://example.com"


async def test_create_duplicate_url(client):
    await client.post("/api/bookmarks", json={"url": "https://dup.com"})
    resp = await client.post("/api/bookmarks", json={"url": "https://dup.com"})
    assert resp.status_code == 409


async def test_list_bookmarks(client):
    await client.post("/api/bookmarks", json={"url": "https://a.com"})
    await client.post("/api/bookmarks", json={"url": "https://b.com"})
    resp = await client.get("/api/bookmarks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


async def test_get_bookmarks_search(client, db):
    await db.execute(
        "INSERT INTO bookmarks (url, title, description) VALUES (?, ?, ?)",
        ("https://python.org", "Python Language", "Programming language"),
    )
    await db.execute(
        "INSERT INTO bookmarks (url, title, description) VALUES (?, ?, ?)",
        ("https://rust-lang.org", "Rust Language", "Systems programming"),
    )
    await db.commit()

    resp = await client.get("/api/bookmarks", params={"search": "python"})
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Python Language"


async def test_get_bookmarks_by_tag(client, db):
    await db.execute(
        "INSERT INTO bookmarks (url, tags) VALUES (?, ?)",
        ("https://a.com", "python,web"),
    )
    await db.execute(
        "INSERT INTO bookmarks (url, tags) VALUES (?, ?)",
        ("https://b.com", "rust,systems"),
    )
    await db.commit()

    resp = await client.get("/api/bookmarks", params={"tag": "python"})
    data = resp.json()
    assert len(data) == 1
    assert data[0]["url"] == "https://a.com"


async def test_update_bookmark(client, db):
    await db.execute(
        "INSERT INTO bookmarks (url, title) VALUES (?, ?)",
        ("https://edit.com", "Old Title"),
    )
    await db.commit()

    row = await db.execute("SELECT id FROM bookmarks WHERE url = ?", ("https://edit.com",))
    bookmark = await row.fetchone()

    resp = await client.put(
        f"/api/bookmarks/{bookmark['id']}",
        json={"title": "New Title", "description": "Updated desc", "tags": "new,tags"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "New Title"
    assert data["description"] == "Updated desc"
    assert data["tags"] == "new,tags"


async def test_delete_bookmark(client, db):
    await db.execute("INSERT INTO bookmarks (url) VALUES (?)", ("https://delete.com",))
    await db.commit()
    row = await db.execute("SELECT id FROM bookmarks WHERE url = ?", ("https://delete.com",))
    bookmark = await row.fetchone()

    # Without password should be rejected when delete_password is configured
    with patch.object(settings, "delete_password", "secret"):
        resp = await client.delete(f"/api/bookmarks/{bookmark['id']}")
        assert resp.status_code == 401

        resp = await client.delete(
            f"/api/bookmarks/{bookmark['id']}",
            headers={"X-Delete-Password": "wrong"}
        )
        assert resp.status_code == 401

        resp = await client.delete(
            f"/api/bookmarks/{bookmark['id']}",
            headers={"X-Delete-Password": "secret"}
        )
        assert resp.status_code == 204

    row = await db.execute("SELECT * FROM bookmarks WHERE id = ?", (bookmark["id"],))
    assert await row.fetchone() is None


async def test_analytics_page(client):
    resp = await client.get("/analytics")
    assert resp.status_code == 200
    assert "Bookmarks" in resp.text


async def test_analytics_page_has_collection_map_panel(client):
    resp = await client.get("/analytics")
    assert resp.status_code == 200
    assert "Collection map" in resp.text
    assert 'x-html="galaxySvg"' in resp.text


async def test_index_page_has_constellation_banner(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert 'x-html="constellationSvg"' in resp.text


async def test_get_analytics_empty(client):
    resp = await client.get("/api/analytics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_bookmarks"] == 0
    assert data["timeline"] == []
    assert data["top_tags"] == []
    assert data["top_domains"] == []


async def test_get_analytics(client, db):
    await db.execute(
        "INSERT INTO bookmarks (url, tags, created_at) VALUES (?, ?, ?)",
        ("https://a.example.com", "python,web", "2020-01-15 10:00:00"),
    )
    await db.execute(
        "INSERT INTO bookmarks (url, tags, created_at) VALUES (?, ?, ?)",
        ("https://www.a.example.com", "python", "2020-01-20 10:00:00"),
    )
    await db.execute(
        "INSERT INTO bookmarks (url, tags, created_at) VALUES (?, ?, ?)",
        ("https://b.example.com", "rust", "2020-03-05 10:00:00"),
    )
    await db.commit()

    resp = await client.get("/api/analytics")
    assert resp.status_code == 200
    data = resp.json()

    assert data["total_bookmarks"] == 3
    assert data["total_tags"] == 3
    # www. is normalized away, so both a.example.com bookmarks share one domain.
    assert data["total_domains"] == 2

    tags = {t["tag"]: t["count"] for t in data["top_tags"]}
    assert tags == {"python": 2, "web": 1, "rust": 1}

    domains = {d["domain"]: d["count"] for d in data["top_domains"]}
    assert domains == {"a.example.com": 2, "b.example.com": 1}

    # Timeline is zero-filled from the first to the last bookmark's month,
    # including the empty February between them.
    periods = {pt["period"]: pt["count"] for pt in data["timeline"]}
    assert periods["2020-01"] == 2
    assert periods["2020-02"] == 0
    assert periods["2020-03"] == 1
    assert [pt["period"] for pt in data["timeline"]] == ["2020-01", "2020-02", "2020-03"]


def _emb(*weights) -> bytes:
    vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    for i, w in enumerate(weights):
        vec[i] = w
    return vec.tobytes()


async def _add(db, url, title, tags, embedding):
    await db.execute(
        "INSERT INTO bookmarks (url, title, tags, embedding) VALUES (?, ?, ?, ?)",
        (url, title, tags, embedding),
    )
    await db.commit()


async def test_analytics_map_empty(client):
    resp = await client.get("/api/analytics/map")
    assert resp.status_code == 200
    assert resp.json() == {"points": [], "clusters": []}


async def test_analytics_map_below_three_embeddings(client, db):
    await _add(db, "https://a.com", "A", "x", _emb(1.0))
    await _add(db, "https://b.com", "B", "y", _emb(0.0, 1.0))
    resp = await client.get("/api/analytics/map")
    assert resp.status_code == 200
    assert resp.json() == {"points": [], "clusters": []}


async def test_analytics_map_projects_points_and_clusters(client, db):
    await _add(db, "https://a.com", "Alpha", "ml", _emb(1.0))
    await _add(db, "https://www.b.com", "Beta", "ml", _emb(0.0, 1.0))
    await _add(db, "https://c.com", "Gamma", "cooking", _emb(0.0, 0.0, 1.0))
    await _add(db, "https://d.com", "Delta", "", _emb(0.3, 0.2, 0.1, 0.4))

    resp = await client.get("/api/analytics/map")
    assert resp.status_code == 200
    data = resp.json()

    assert len(data["points"]) == 4
    for point in data["points"]:
        assert set(point) == {"id", "x", "y", "title", "domain", "url", "tag"}
        assert 0.0 <= point["x"] <= 1.0
        assert 0.0 <= point["y"] <= 1.0

    by_title = {p["title"]: p for p in data["points"]}
    assert by_title["Beta"]["domain"] == "b.com"  # www. stripped
    assert by_title["Delta"]["tag"] is None       # empty tags -> None

    assert data["clusters"] == [
        {"tag": "ml", "count": 2},
        {"tag": "cooking", "count": 1},
    ]


async def test_get_tags(client, db):
    await db.execute("INSERT INTO bookmarks (url, tags) VALUES (?, ?)", ("https://a.com", "python,web"))
    await db.execute("INSERT INTO bookmarks (url, tags) VALUES (?, ?)", ("https://b.com", "python,api"))
    await db.execute("INSERT INTO bookmarks (url) VALUES (?)", ("https://notags.com",))
    await db.commit()

    resp = await client.get("/api/tags")
    assert resp.status_code == 200
    data = resp.json()
    # total counts bookmarks (sidebar "All bookmarks"), not tag occurrences
    assert data["total"] == 3
    tags = {t["tag"]: t["count"] for t in data["tags"]}
    assert tags["python"] == 2
    assert tags["web"] == 1
    assert tags["api"] == 1
