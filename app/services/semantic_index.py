"""Nearest-neighbor search over bookmark embeddings.

Deliberately brute force: every embedding is loaded into a per-worker numpy
matrix, normalized once, and queries are a single matmul. For a personal
bookmark collection (hundreds to low thousands of rows at 384 dims) that is
sub-millisecond — the same "in-memory set of embeddings" approach the
hypothetical-classifications writeup uses, without a vector DB.

The cache re-reads the bookmarks table when older than
`semantic_cache_ttl_seconds` (gunicorn workers don't share memory) or when a
write in this worker calls invalidate().
"""
import logging
import time

import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 384


def decode_embedding(blob: bytes | None) -> np.ndarray | None:
    if not blob:
        return None
    vec = np.frombuffer(blob, dtype=np.float32)
    if vec.size != EMBEDDING_DIM:
        return None
    return vec


class SemanticIndex:
    def __init__(self):
        self._ids: list[int] = []
        self._matrix: np.ndarray | None = None  # rows are L2-normalized
        self._loaded_at: float = 0.0

    @property
    def is_stale(self) -> bool:
        return (
            self._matrix is None
            or time.monotonic() - self._loaded_at > settings.semantic_cache_ttl_seconds
        )

    async def refresh(self, db) -> None:
        cursor = await db.execute("SELECT id, embedding FROM bookmarks WHERE embedding IS NOT NULL")
        rows = await cursor.fetchall()
        ids: list[int] = []
        vectors: list[np.ndarray] = []
        for row in rows:
            vec = decode_embedding(row["embedding"])
            if vec is not None:
                ids.append(row["id"])
                vectors.append(vec)
        if vectors:
            matrix = np.vstack(vectors)
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            self._matrix = matrix / np.where(norms == 0, 1.0, norms)
        else:
            self._matrix = np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        self._ids = ids
        self._loaded_at = time.monotonic()

    async def search(
        self,
        db,
        query_vector: list[float],
        *,
        exclude_ids: set[int] | None = None,
    ) -> list[tuple[int, float]]:
        """Top semantic matches as (bookmark_id, cosine similarity), best first."""
        if self.is_stale:
            await self.refresh(db)

        query = np.asarray(query_vector, dtype=np.float32)
        norm = np.linalg.norm(query)
        if norm == 0 or self._matrix is None or self._matrix.shape[0] == 0:
            return []
        query = query / norm

        sims = self._matrix @ query
        order = np.argsort(sims)[::-1]
        results: list[tuple[int, float]] = []
        threshold = settings.semantic_score_threshold
        for idx in order:
            score = float(sims[idx])
            if score < threshold:
                break
            bookmark_id = self._ids[idx]
            if exclude_ids and bookmark_id in exclude_ids:
                continue
            results.append((bookmark_id, round(score, 4)))
            if len(results) >= settings.semantic_search_limit:
                break
        return results


def invalidate_index(app_state) -> None:
    """Force the next search to re-read embeddings from the database."""
    index = getattr(app_state, "semantic_index", None)
    if index is not None:
        index._loaded_at = 0.0


async def get_semantic_index(app_state) -> SemanticIndex:
    if not hasattr(app_state, "semantic_index"):
        app_state.semantic_index = SemanticIndex()
    return app_state.semantic_index
