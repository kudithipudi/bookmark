import pytest
from unittest.mock import patch


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
    import os
    await db.execute("INSERT INTO bookmarks (url) VALUES (?)", ("https://delete.com",))
    await db.commit()
    row = await db.execute("SELECT id FROM bookmarks WHERE url = ?", ("https://delete.com",))
    bookmark = await row.fetchone()

    # Without password should be rejected when DELETE_PASSWORD is set
    with patch.dict(os.environ, {"DELETE_PASSWORD": "secret"}):
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


async def test_get_tags(client, db):
    await db.execute("INSERT INTO bookmarks (url, tags) VALUES (?, ?)", ("https://a.com", "python,web"))
    await db.execute("INSERT INTO bookmarks (url, tags) VALUES (?, ?)", ("https://b.com", "python,api"))
    await db.execute("INSERT INTO bookmarks (url, tags) VALUES (?, ?)", ("https://c.com", "web"))
    await db.commit()

    resp = await client.get("/api/tags")
    assert resp.status_code == 200
    data = resp.json()
    tags = {t["tag"]: t["count"] for t in data}
    assert tags["python"] == 2
    assert tags["web"] == 2
    assert tags["api"] == 1
