import asyncio
import socket

import httpx
import pytest
from unittest.mock import AsyncMock

from app.config import settings
from app.services import linkcheck
from app.services.linkcheck import check_url, classify


# --- classify() ---------------------------------------------------------------

def test_classify_reachable():
    assert classify(200, "https://a.com", "https://a.com/") == "ok"
    assert classify(204, "https://a.com", None) == "ok"
    assert classify(206, "https://a.com", "https://www.a.com/") == "ok"  # same host sans www
    assert classify(200, "https://a.com", "https://elsewhere.com/") == "moved"


def test_classify_dead_vs_uncertain():
    assert classify(404, "https://a.com", None) == "broken"
    assert classify(410, "https://a.com", None) == "broken"
    assert classify(418, "https://a.com", None) == "broken"   # odd 4xx -> dead
    assert classify(403, "https://a.com", None) == "uncertain"  # bot wall
    assert classify(429, "https://a.com", None) == "uncertain"  # rate limited
    assert classify(503, "https://a.com", None) == "uncertain"  # transient
    assert classify(None, "https://a.com", None) == "uncertain"


# --- check_url() -------------------------------------------------------------

def _resp(status_code: int, url: str) -> AsyncMock:
    r = AsyncMock(spec=httpx.Response)
    r.status_code = status_code
    r.url = httpx.URL(url)
    return r


async def test_check_url_ok_uses_head_only():
    client = AsyncMock()
    client.head = AsyncMock(return_value=_resp(200, "https://a.com/"))
    assert await check_url(client, "https://a.com") == ("ok", 200, "https://a.com/")
    client.get.assert_not_called()


async def test_check_url_falls_back_to_get_when_head_rejected():
    client = AsyncMock()
    client.head = AsyncMock(return_value=_resp(405, "https://a.com"))
    client.get = AsyncMock(return_value=_resp(200, "https://a.com/"))
    bucket, code, _ = await check_url(client, "https://a.com")
    assert (bucket, code) == ("ok", 200)
    client.get.assert_called_once()


async def test_check_url_404_is_broken():
    client = AsyncMock()
    client.head = AsyncMock(return_value=_resp(404, "https://a.com"))
    client.get = AsyncMock(return_value=_resp(404, "https://a.com"))
    assert (await check_url(client, "https://a.com"))[:2] == ("broken", 404)


async def test_check_url_timeout_is_uncertain():
    client = AsyncMock()
    client.head = AsyncMock(side_effect=httpx.TimeoutException("slow"))
    client.get = AsyncMock(side_effect=httpx.TimeoutException("slow"))
    assert await check_url(client, "https://a.com") == ("uncertain", None, None)


async def test_check_url_dns_failure_is_broken():
    err = httpx.ConnectError("no address")
    err.__cause__ = socket.gaierror("Name or service not known")
    client = AsyncMock()
    client.head = AsyncMock(side_effect=err)
    client.get = AsyncMock(side_effect=err)
    assert await check_url(client, "https://gone.example") == ("broken", None, None)


async def test_check_url_detects_move_to_new_host():
    client = AsyncMock()
    client.head = AsyncMock(return_value=_resp(200, "https://new-place.com/x"))
    bucket, _, final = await check_url(client, "https://old-place.com/x")
    assert bucket == "moved"
    assert final == "https://new-place.com/x"


async def test_check_url_skips_non_http():
    client = AsyncMock()
    assert await check_url(client, "ftp://a.com") == ("uncertain", None, None)
    client.head.assert_not_called()


# --- end-to-end sweep via the API -------------------------------------------

async def _await_run():
    from app.main import app
    await app.state.link_check_task


async def test_link_check_flow(client, db, monkeypatch):
    await db.execute("INSERT INTO bookmarks (url) VALUES ('https://ok.com')")
    await db.execute("INSERT INTO bookmarks (url) VALUES ('https://dead.com')")
    await db.commit()

    async def fake_check(_client, url):
        return ("broken", 404, url) if "dead" in url else ("ok", 200, url)

    monkeypatch.setattr(linkcheck, "check_url", fake_check)

    resp = await client.post("/api/admin/link-check")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2
    await _await_run()

    cur = await db.execute(
        "SELECT url, link_status, link_fail_count FROM bookmarks ORDER BY url"
    )
    by_url = {r["url"]: r for r in await cur.fetchall()}
    assert by_url["https://ok.com"]["link_status"] == "ok"
    assert by_url["https://dead.com"]["link_status"] == "broken"
    assert by_url["https://dead.com"]["link_fail_count"] == 1

    # A deterministic 404 counts as broken after a single sweep (threshold 1).
    health = (await client.get("/api/link-health")).json()
    assert (health["broken"], health["review"], health["checked"]) == (1, 0, 2)

    # A repeat sweep just bumps the fail count, still broken.
    await client.post("/api/admin/link-check")
    await _await_run()
    cur = await db.execute(
        "SELECT link_fail_count FROM bookmarks WHERE url = 'https://dead.com'"
    )
    assert (await cur.fetchone())["link_fail_count"] == 2

    listing = (await client.get("/api/bookmarks?status=broken")).json()
    assert [b["url"] for b in listing] == ["https://dead.com"]


async def test_uncertain_never_auto_promotes_to_broken(client, db, monkeypatch):
    """A bot wall (403) stays 'uncertain' no matter how many sweeps fail —
    only the deterministic-dead bucket ('broken') is ever confirmed."""
    await db.execute("INSERT INTO bookmarks (url) VALUES ('https://walled.com')")
    await db.commit()

    async def fake_check(_client, url):
        return ("uncertain", 403, None)

    monkeypatch.setattr(linkcheck, "check_url", fake_check)
    for _ in range(3):
        await client.post("/api/admin/link-check")
        await _await_run()

    health = (await client.get("/api/link-health")).json()
    assert health["broken"] == 0
    assert health["review"] == 1
    cur = await db.execute("SELECT link_status FROM bookmarks")
    assert (await cur.fetchone())["link_status"] == "uncertain"


async def test_link_check_recovery_resets_fail_count(client, db, monkeypatch):
    await db.execute(
        "INSERT INTO bookmarks (url, link_status, link_fail_count) "
        "VALUES ('https://flaky.com', 'broken', 5)"
    )
    await db.commit()

    async def fake_check(_client, url):
        return ("ok", 200, url)

    monkeypatch.setattr(linkcheck, "check_url", fake_check)
    await client.post("/api/admin/link-check")
    await _await_run()

    cur = await db.execute("SELECT link_status, link_fail_count FROM bookmarks")
    row = await cur.fetchone()
    assert row["link_status"] == "ok"
    assert row["link_fail_count"] == 0


async def test_link_check_requires_admin_password(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "s3cret")
    assert (await client.post("/api/admin/link-check")).status_code == 401
    assert (
        await client.post("/api/admin/link-check", headers={"X-Admin-Password": "nope"})
    ).status_code == 401
    resp = await client.post(
        "/api/admin/link-check", headers={"X-Admin-Password": "s3cret"}
    )
    assert resp.status_code == 200
    await _await_run()  # let the (empty) sweep finish cleanly


async def test_link_check_conflicts_while_running(client, db, monkeypatch):
    await db.execute("INSERT INTO bookmarks (url) VALUES ('https://a.com')")
    await db.commit()

    gate = asyncio.Event()

    async def slow_check(_client, url):
        await gate.wait()
        return ("ok", 200, url)

    monkeypatch.setattr(linkcheck, "check_url", slow_check)

    assert (await client.post("/api/admin/link-check")).status_code == 200
    assert (await client.post("/api/admin/link-check")).status_code == 409
    gate.set()
    await _await_run()


async def test_update_bookmark_url_clears_link_health(client, db):
    await db.execute(
        "INSERT INTO bookmarks (url, link_status, link_status_code, link_final_url, link_fail_count) "
        "VALUES ('https://old.com', 'moved', 200, 'https://new.com', 0)"
    )
    await db.commit()
    cur = await db.execute("SELECT id FROM bookmarks")
    bid = (await cur.fetchone())["id"]

    resp = await client.put(f"/api/bookmarks/{bid}", json={"url": "https://new.com"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["url"] == "https://new.com"
    assert body["link_status"] is None
    assert body["link_fail_count"] == 0


async def test_update_bookmark_url_rejects_duplicate(client, db):
    await db.execute("INSERT INTO bookmarks (url) VALUES ('https://a.com')")
    await db.execute("INSERT INTO bookmarks (url) VALUES ('https://b.com')")
    await db.commit()
    cur = await db.execute("SELECT id FROM bookmarks WHERE url = 'https://a.com'")
    bid = (await cur.fetchone())["id"]

    resp = await client.put(f"/api/bookmarks/{bid}", json={"url": "https://b.com"})
    assert resp.status_code == 409
