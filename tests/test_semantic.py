"""Semantic search: embedding storage, nearest-neighbor ranking, and the
hybrid exact+semantic merge in the bookmarks endpoint."""
import numpy as np
import pytest
from unittest.mock import patch

from app.config import settings
from app.db import init_db
from app.services.embeddings import build_embedding_text
from app.services.semantic_index import EMBEDDING_DIM, SemanticIndex, decode_embedding


def make_vector(*weights) -> bytes:
    vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    for i, w in enumerate(weights):
        vec[i] = w
    return vec.tobytes()


async def _insert(db, url, title=None, description=None, tags=None, embedding=None):
    cursor = await db.execute(
        "INSERT INTO bookmarks (url, title, description, tags, embedding) VALUES (?, ?, ?, ?, ?)",
        (url, title, description, tags, embedding),
    )
    await db.commit()
    return cursor.lastrowid


# --- unit: text building / blob round-trip -------------------------------


def test_build_embedding_text_joins_parts():
    text = build_embedding_text("Python", "Learn Python", "python,tutorial")
    assert text == "Python Learn Python python,tutorial"


def test_build_embedding_text_skips_empty():
    assert build_embedding_text(None, "", "  ") == ""


def test_blob_round_trip():
    blob = make_vector(0.5, -1.25)
    decoded = decode_embedding(blob)
    assert decoded[0] == pytest.approx(0.5)
    assert decoded[1] == pytest.approx(-1.25)


def test_decode_rejects_wrong_dim_or_empty():
    assert decode_embedding(b"") is None
    assert decode_embedding(np.zeros(8, dtype=np.float32).tobytes()) is None


# --- unit: index ranking --------------------------------------------------


async def test_search_ranks_nearest_neighbor(db):
    id_a = await _insert(db, "https://a.com", title="AI research", embedding=make_vector(1.0))
    id_b = await _insert(db, "https://b.com", title="Cooking", embedding=make_vector(0.0, 1.0))

    # Query points mostly along A's direction.
    query = [0.95, 0.31] + [0.0] * (EMBEDDING_DIM - 2)
    index = SemanticIndex()
    hits = await index.search(db, query)

    assert [bookmark_id for bookmark_id, _ in hits][0] == id_a
    assert all(score >= settings.semantic_score_threshold for _, score in hits)
    scores = dict(hits)
    assert id_b not in scores or scores[id_a] > scores[id_b]


async def test_search_respects_threshold(db):
    await _insert(db, "https://a.com", embedding=make_vector(1.0))
    query = [0.4, 0.9] + [0.0] * (EMBEDDING_DIM - 2)  # cos ~0.41 < threshold

    index = SemanticIndex()
    hits = await index.search(db, query)
    assert hits == []


async def test_search_excludes_exact_ids(db):
    id_a = await _insert(db, "https://a.com", embedding=make_vector(1.0))

    index = SemanticIndex()
    hits = await index.search(db, [1.0] + [0.0] * (EMBEDDING_DIM - 1), exclude_ids={id_a})
    assert hits == []


async def test_index_refresh_picks_up_new_rows(db):
    index = SemanticIndex()
    assert (await index.search(db, [1.0] + [0.0] * (EMBEDDING_DIM - 1))) == []

    await _insert(db, "https://late.com", embedding=make_vector(1.0))
    index._loaded_at = 0.0  # simulate TTL expiry instead of sleeping
    hits = await index.search(db, [1.0] + [0.0] * (EMBEDDING_DIM - 1))
    assert len(hits) == 1


# --- endpoint: hybrid merge ----------------------------------------------


async def test_hybrid_search_exact_first_then_semantic(client, db):
    await _insert(db, "https://py.org", title="Python Language", description="Programming")
    await _insert(
        db,
        "https://ai-journal.example.com",
        title="Neural Networks Journal",
        description="Deep learning and LLM papers",
        embedding=make_vector(1.0),
    )

    async def fake_embed_query(search):
        return [0.99] + [0.14] + [0.0] * (EMBEDDING_DIM - 2)

    with patch("app.main.embed_query", side_effect=fake_embed_query):
        resp = await client.get("/api/bookmarks", params={"search": "python"})

    data = resp.json()
    assert [b["match"] for b in data] == ["exact", "semantic"]
    assert data[0]["title"] == "Python Language"
    assert "score" not in data[0]
    assert data[1]["title"] == "Neural Networks Journal"
    assert data[1]["score"] > settings.semantic_score_threshold


async def test_tags_scoped_to_search_results(client, db):
    # Exact keyword hit, tagged "language".
    await _insert(db, "https://py.org", title="Python Language", tags="language")
    # Semantic-only hit (no keyword overlap), tagged "ml".
    await _insert(
        db,
        "https://ai-journal.example.com",
        title="Neural Networks Journal",
        tags="ml",
        embedding=make_vector(1.0),
    )
    # Unrelated bookmark that shouldn't appear in either search result.
    await _insert(db, "https://cooking.example.com", title="Recipes", tags="cooking")

    async def fake_embed_query(search):
        return [0.99] + [0.14] + [0.0] * (EMBEDDING_DIM - 2)

    with patch("app.main.embed_query", side_effect=fake_embed_query):
        resp = await client.get("/api/tags", params={"search": "python"})

    data = resp.json()
    tags = {t["tag"]: t["count"] for t in data["tags"]}
    assert tags == {"language": 1, "ml": 1}
    # "total" always reflects the whole library, independent of the search.
    assert data["total"] == 3


async def test_tags_search_scoping_degrades_gracefully_without_embeddings(client, db):
    await _insert(db, "https://py.org", title="Python Language", tags="language")

    async def none_embed_query(search):
        return None

    with patch("app.main.embed_query", side_effect=none_embed_query):
        resp = await client.get("/api/tags", params={"search": "python"})

    assert resp.status_code == 200
    tags = {t["tag"]: t["count"] for t in resp.json()["tags"]}
    assert tags == {"language": 1}


async def test_no_search_param_has_no_match_field(client, db):
    await _insert(db, "https://plain.com", title="Plain")
    resp = await client.get("/api/bookmarks")
    assert all("match" not in b for b in resp.json())


async def test_tag_filter_skips_semantic_pass(client, db):
    await _insert(
        db,
        "https://vec.com",
        tags="cooking",
        embedding=make_vector(1.0),
    )

    async def fail_embed_query(search):  # pragma: no cover
        raise AssertionError("embedding should not run when tag filter is active")

    with patch("app.main.embed_query", side_effect=fail_embed_query):
        resp = await client.get("/api/bookmarks", params={"tag": "cooking"})

    data = resp.json()
    assert len(data) == 1
    assert "match" not in data[0]


async def test_search_degrades_gracefully_without_embeddings(client, db):
    await _insert(db, "https://x.com", title="Exact only")

    async def none_embed_query(search):
        return None

    with patch("app.main.embed_query", side_effect=none_embed_query):
        resp = await client.get("/api/bookmarks", params={"search": "exact"})

    data = resp.json()
    assert len(data) == 1
    assert data[0]["match"] == "exact"


# --- write paths ----------------------------------------------------------


async def test_create_bookmark_stores_embedding(client, db):
    blob = make_vector(1.0)

    async def fake_embed(title, description, tags):
        return blob

    with patch("app.main.embed_bookmark", side_effect=fake_embed):
        resp = await client.post("/api/bookmarks", json={"url": "https://embed.com"})
    assert resp.status_code == 201

    row = await db.execute("SELECT embedding FROM bookmarks WHERE url = ?", ("https://embed.com",))
    assert (await row.fetchone())["embedding"] == blob


async def test_update_reembeds_changed_content(client, db):
    old_blob = make_vector(1.0)
    new_blob = make_vector(0.0, 1.0)
    bookmark_id = await _insert(db, "https://edit-emb.com", title="Old", embedding=old_blob)

    calls = []

    async def fake_embed(title, description, tags):
        calls.append((title, description, tags))
        return new_blob

    with patch("app.main.embed_bookmark", side_effect=fake_embed):
        resp = await client.put(f"/api/bookmarks/{bookmark_id}", json={"title": "New Title"})
    assert resp.status_code == 200
    assert calls == [("New Title", None, None)]

    row = await db.execute("SELECT embedding FROM bookmarks WHERE id = ?", (bookmark_id,))
    assert (await row.fetchone())["embedding"] == new_blob


async def test_update_without_content_change_keeps_embedding(client, db):
    blob = make_vector(1.0)
    bookmark_id = await _insert(db, "https://keep.com", title="T", embedding=blob)

    async def fail_embed(title, description, tags):  # pragma: no cover
        raise AssertionError("should not re-embed when content unchanged")

    with patch("app.main.embed_bookmark", side_effect=fail_embed):
        resp = await client.put(f"/api/bookmarks/{bookmark_id}", json={})
    assert resp.status_code == 200

    row = await db.execute("SELECT embedding FROM bookmarks WHERE id = ?", (bookmark_id,))
    assert (await row.fetchone())["embedding"] == blob


# --- migration -------------------------------------------------------------


async def test_init_db_migrates_missing_embedding_column(tmp_path):
    import aiosqlite

    db_path = str(tmp_path / "legacy.db")
    conn = await aiosqlite.connect(db_path)
    await conn.execute(
        """
        CREATE TABLE bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            title TEXT,
            description TEXT,
            favicon TEXT,
            tags TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await conn.execute("INSERT INTO bookmarks (url) VALUES ('https://legacy.com')")
    await conn.commit()
    await conn.close()

    await init_db(db_path)

    conn = await aiosqlite.connect(db_path)
    cursor = await conn.execute("PRAGMA table_info(bookmarks)")
    columns = {row[1] for row in await cursor.fetchall()}
    await conn.close()
    assert "embedding" in columns
