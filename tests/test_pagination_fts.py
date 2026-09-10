"""Pagination contract for /api/bookmarks, FTS5-backed search, the
bookmarks_fts sync triggers, and the cross-connection data_version refresh."""
import numpy as np
import pytest
from unittest.mock import patch

import aiosqlite

from app.db import (
    fts_match_query,
    SQL_CREATE_TABLE,
    SQL_CREATE_RATE_LIMIT_TABLE,
    SQL_CREATE_RATE_LIMIT_INDEX,
    SQL_CREATE_LINK_CHECK_RUNS_TABLE,
    SQL_CREATE_BOOKMARKS_CREATED_AT_INDEX,
    SQL_CREATE_FTS_TABLE,
    SQL_CREATE_FTS_TRIGGERS,
)
from app.services.semantic_index import EMBEDDING_DIM, SemanticIndex


async def _insert(db, url, title=None, description=None, tags="", created_at=None):
    if created_at is None:
        await db.execute(
            "INSERT INTO bookmarks (url, title, description, tags) VALUES (?, ?, ?, ?)",
            (url, title, description, tags),
        )
    else:
        await db.execute(
            "INSERT INTO bookmarks (url, title, description, tags, created_at) VALUES (?, ?, ?, ?, ?)",
            (url, title, description, tags, created_at),
        )
    await db.commit()


# --- fts_match_query helper -------------------------------------------------


def test_fts_match_query_quotes_and_prefixes_each_token():
    assert fts_match_query("git hub") == '"git"* "hub"*'


def test_fts_match_query_strips_special_chars():
    # quotes, parens, star, colon, NEAR/AND punctuation all removed
    assert fts_match_query('foo* (bar) "baz":') == '"foo"* "bar"* "baz"*'


def test_fts_match_query_returns_none_when_nothing_usable():
    assert fts_match_query("") is None
    assert fts_match_query("   ") is None
    assert fts_match_query('*** ()') is None


# --- pagination contract ---------------------------------------------------


async def test_pagination_headers_and_slicing(client, db):
    for i in range(5):
        await _insert(
            db, f"https://e{i}.com", title=f"Item {i}",
            created_at=f"2020-01-0{i + 1} 10:00:00",
        )

    r = await client.get("/api/bookmarks", params={"limit": 2, "offset": 0})
    assert r.status_code == 200
    body = r.json()
    assert [b["title"] for b in body] == ["Item 4", "Item 3"]  # created_at DESC
    assert r.headers["x-total-count"] == "5"
    assert r.headers["x-has-more"] == "true"

    r = await client.get("/api/bookmarks", params={"limit": 2, "offset": 2})
    assert [b["title"] for b in r.json()] == ["Item 2", "Item 1"]
    assert r.headers["x-has-more"] == "true"

    r = await client.get("/api/bookmarks", params={"limit": 2, "offset": 4})
    assert [b["title"] for b in r.json()] == ["Item 0"]
    assert r.headers["x-total-count"] == "5"
    assert r.headers["x-has-more"] == "false"


async def test_pagination_clamps_out_of_range_params(client, db):
    await _insert(db, "https://a.com", title="only")
    r = await client.get("/api/bookmarks", params={"limit": 9999, "offset": -5})
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.headers["x-has-more"] == "false"


async def test_default_response_is_a_bare_array(client, db):
    await _insert(db, "https://a.com", title="a")
    r = await client.get("/api/bookmarks")
    assert isinstance(r.json(), list)
    assert r.headers["x-total-count"] == "1"


async def test_semantic_pass_only_on_first_page(client, db):
    await _insert(db, "https://py.org", title="Python Language")
    await db.execute(
        "INSERT INTO bookmarks (url, title, embedding) VALUES (?, ?, ?)",
        ("https://ai.example.com", "Neural Nets", _vec(1.0)),
    )
    await db.commit()

    async def fake_embed_query(search):
        return [0.99, 0.14] + [0.0] * (EMBEDDING_DIM - 2)

    with patch("app.main.embed_query", side_effect=fake_embed_query):
        first = await client.get("/api/bookmarks", params={"search": "python", "offset": 0})
        later = await client.get("/api/bookmarks", params={"search": "python", "offset": 1})

    assert [b["match"] for b in first.json()] == ["exact", "semantic"]
    # offset > 0: exact matches are exhausted and the semantic pass is skipped
    assert later.json() == []


async def test_semantic_pass_skipped_entirely_on_later_pages(client, db):
    await _insert(db, "https://py.org", title="Python Language")

    async def boom(search):  # pragma: no cover
        raise AssertionError("embed_query must not run for offset > 0")

    with patch("app.main.embed_query", side_effect=boom):
        r = await client.get("/api/bookmarks", params={"search": "python", "offset": 5})
    assert r.status_code == 200


# --- FTS-backed search ----------------------------------------------------


async def test_fts_search_multiword_is_implicit_and(client, db):
    await _insert(db, "https://a.com", title="Machine Learning Guide")
    await _insert(db, "https://b.com", title="Machine Shop Manual")
    await _insert(db, "https://c.com", title="Deep Learning Papers")

    r = await client.get("/api/bookmarks", params={"search": "machine learning"})
    titles = [b["title"] for b in r.json() if b["match"] == "exact"]
    assert titles == ["Machine Learning Guide"]


async def test_fts_search_is_prefix_matched(client, db):
    await _insert(db, "https://a.com", title="Programming languages")
    r = await client.get("/api/bookmarks", params={"search": "program"})
    assert [b["title"] for b in r.json()] == ["Programming languages"]


async def test_fts_search_matches_across_columns(client, db):
    await _insert(db, "https://kubernetes.io", title="K8s", description="container orchestration")
    await _insert(db, "https://other.com", title="Other", tags="kubernetes,ops")

    r = await client.get("/api/bookmarks", params={"search": "kubernetes"})
    urls = {b["url"] for b in r.json()}
    assert urls == {"https://kubernetes.io", "https://other.com"}


async def test_fts_search_falls_back_to_like_on_unusable_query(client, db):
    await _insert(db, "https://a.com", title="C++ pointers")
    # "c++" -> tokens stripped of '+' -> '"c"*'; still fine. A pure-punctuation
    # query yields no usable tokens and must fall back to LIKE.
    r = await client.get("/api/bookmarks", params={"search": "+++"})
    assert r.status_code == 200
    assert r.json() == []  # LIKE '%+++%' matches nothing, but no error


# --- bookmarks_fts sync triggers ----------------------------------------


async def test_fts_triggers_sync_on_insert_update_delete(db):
    async def match(term):
        cur = await db.execute(
            "SELECT rowid FROM bookmarks_fts WHERE bookmarks_fts MATCH ?", (term,)
        )
        return {r[0] for r in await cur.fetchall()}

    await _insert(db, "https://x.com", title="Alpha", tags="one")
    row = await (await db.execute("SELECT id FROM bookmarks")).fetchone()
    bid = row[0]
    assert await match("alpha") == {bid}

    await db.execute("UPDATE bookmarks SET title = 'Bravo' WHERE id = ?", (bid,))
    await db.commit()
    assert await match("alpha") == set()
    assert await match("bravo") == {bid}

    await db.execute("DELETE FROM bookmarks WHERE id = ?", (bid,))
    await db.commit()
    assert await match("bravo") == set()


async def test_fts_search_reflects_endpoint_writes(client, db):
    await _insert(db, "https://x.com", title="Findable")
    bid = (await (await db.execute("SELECT id FROM bookmarks")).fetchone())[0]

    r = await client.get("/api/bookmarks", params={"search": "findable"})
    assert len(r.json()) == 1

    async def fake_embed(title, description, tags):
        return None

    with patch("app.main.embed_bookmark", side_effect=fake_embed):
        await client.put(f"/api/bookmarks/{bid}", json={"title": "Renamed"})

    assert (await client.get("/api/bookmarks", params={"search": "findable"})).json() == []
    assert len((await client.get("/api/bookmarks", params={"search": "renamed"})).json()) == 1


# --- cross-connection data_version refresh -----------------------------


def _vec(*weights) -> bytes:
    v = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    for i, w in enumerate(weights):
        v[i] = w
    return v.tobytes()


async def _make_conn(path):
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    return conn


async def test_data_version_forces_refresh_after_other_connection_write(tmp_path):
    path = str(tmp_path / "dv.db")
    setup = await _make_conn(path)
    await setup.execute(SQL_CREATE_TABLE)
    await setup.execute(SQL_CREATE_RATE_LIMIT_TABLE)
    await setup.execute(SQL_CREATE_RATE_LIMIT_INDEX)
    await setup.execute(SQL_CREATE_LINK_CHECK_RUNS_TABLE)
    await setup.execute(SQL_CREATE_BOOKMARKS_CREATED_AT_INDEX)
    await setup.execute(SQL_CREATE_FTS_TABLE)
    for ddl in SQL_CREATE_FTS_TRIGGERS:
        await setup.execute(ddl)
    await setup.commit()
    await setup.close()

    reader = await _make_conn(path)   # stands in for gunicorn worker B
    writer = await _make_conn(path)   # stands in for gunicorn worker A

    await writer.execute(
        "INSERT INTO bookmarks (url, embedding) VALUES (?, ?)",
        ("https://first.com", _vec(1.0)),
    )
    await writer.commit()

    index = SemanticIndex()
    hits = await index.search(reader, [1.0] + [0.0] * (EMBEDDING_DIM - 1))
    assert len(hits) == 1
    loaded_version = index._data_version
    assert loaded_version is not None

    # Worker A commits another row. Worker B's TTL has NOT expired, but its
    # data_version check must notice and reload.
    await writer.execute(
        "INSERT INTO bookmarks (url, embedding) VALUES (?, ?)",
        ("https://second.com", _vec(1.0)),
    )
    await writer.commit()

    await index.ensure_fresh(reader)
    assert index._data_version != loaded_version
    assert len(index._ids) == 2

    await reader.close()
    await writer.close()
