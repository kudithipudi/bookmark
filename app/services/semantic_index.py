"""Nearest-neighbor search over bookmark embeddings.

Deliberately brute force: every embedding is loaded into a per-worker numpy
matrix, normalized once, and queries are a single matmul. For a personal
bookmark collection (hundreds to low thousands of rows at 384 dims) that is
sub-millisecond — the same "in-memory set of embeddings" approach the
hypothetical-classifications writeup uses, without a vector DB.

The cache re-reads the bookmarks table when SQLite's `PRAGMA data_version`
shows another connection has committed (this is how one gunicorn worker
notices another's writes — they don't share memory), when a write in this
worker calls invalidate(), or, as a coarse fallback, when it is older than
`semantic_cache_ttl_seconds`.
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
        # SQLite PRAGMA data_version at the moment we last loaded. It changes
        # only when *another* connection commits, so comparing it on each use
        # is how this worker notices a sibling worker's write. None forces a
        # refresh on the next check.
        self._data_version: int | None = None
        # A single-assignment (matrix, ids, loaded_at) triple that refresh()
        # publishes atomically. project_2d() runs in a worker thread (see the
        # to_thread call in get_analytics_map) and reads this once, so a
        # concurrent refresh() on the event loop can never pair an old matrix
        # with a new id list.
        self._snapshot: tuple[np.ndarray | None, list[int], float] = (None, [], 0.0)
        # Memoized project_2d() result, keyed on the loaded_at stamp it was
        # computed from, so refresh() (and invalidate_index) drop it for free.
        self._projection: list[tuple[int, float, float]] | None = None
        self._projection_at: float = -1.0

    @property
    def is_stale(self) -> bool:
        return (
            self._matrix is None
            or time.monotonic() - self._loaded_at > settings.semantic_cache_ttl_seconds
        )

    @staticmethod
    async def _read_data_version(db) -> int | None:
        try:
            cursor = await db.execute("PRAGMA data_version")
            row = await cursor.fetchone()
            return int(row[0]) if row is not None else None
        except Exception:
            return None

    async def ensure_fresh(self, db) -> None:
        """Refresh the cache if it is empty, TTL-expired, or another DB
        connection has committed since we last loaded. Call this before
        reading `_matrix` / `_snapshot` on any request path."""
        if self.is_stale:
            await self.refresh(db)
            return
        version = await self._read_data_version(db)
        if version is not None and version != self._data_version:
            await self.refresh(db)

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
        # Record the DB's data_version *after* the read, so a commit that
        # lands between the SELECT and here just triggers one more refresh.
        self._data_version = await self._read_data_version(db)
        # Publish the coherent triple last, in one assignment, for project_2d().
        self._snapshot = (self._matrix, self._ids, self._loaded_at)

    async def search(
        self,
        db,
        query_vector: list[float],
        *,
        exclude_ids: set[int] | None = None,
    ) -> list[tuple[int, float]]:
        """Top semantic matches as (bookmark_id, cosine similarity), best first."""
        await self.ensure_fresh(db)

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

    def project_2d(self) -> list[tuple[int, float, float]]:
        """(bookmark_id, x, y) for every loaded embedding, projected to 2D
        with PCA (top two principal components) and each axis min-max scaled
        to [0, 1]. Same order as self._ids.

        Returns [] when fewer than 3 embeddings are loaded: PCA on one or two
        points carries no structure, and the caller shows an empty state.
        The caller is responsible for freshness (see search()).

        The result is memoized against the snapshot's loaded_at stamp: the SVD
        is tens of milliseconds at a few hundred rows and closer to a second at
        10k, and nothing about it changes until the index is reloaded.
        """
        matrix, ids, loaded_at = self._snapshot

        if self._projection is not None and self._projection_at == loaded_at:
            return self._projection

        if matrix is None or matrix.shape[0] < 3:
            self._projection = []
            self._projection_at = loaded_at
            return self._projection

        centered = matrix - matrix.mean(axis=0, keepdims=True)
        # SVD of the centered matrix is PCA. full_matrices=False keeps U at
        # (n, min(n, dim)); we take the first two components.
        u, s, _ = np.linalg.svd(centered, full_matrices=False)
        coords = u[:, :2] * s[:2]  # (n, 2)

        def scale(column: np.ndarray) -> np.ndarray:
            low = float(column.min())
            high = float(column.max())
            if high - low < 1e-12:
                return np.full(column.shape, 0.5, dtype=np.float64)
            return (column - low) / (high - low)

        xs = scale(coords[:, 0])
        ys = scale(coords[:, 1])
        self._projection = [
            (int(bid), round(float(px), 4), round(float(py), 4))
            for bid, px, py in zip(ids, xs, ys)
        ]
        self._projection_at = loaded_at
        return self._projection


def invalidate_index(app_state) -> None:
    """Force the next search to re-read embeddings from the database."""
    index = getattr(app_state, "semantic_index", None)
    if index is not None:
        index._loaded_at = 0.0
        # Also drop the data_version stamp so the next ensure_fresh() reloads
        # even if the TTL check somehow passes.
        index._data_version = None
        index._snapshot = (index._snapshot[0], index._snapshot[1], 0.0)
        # Drop the projection memo outright so the 0.0 stamp can't alias a
        # later cache entry keyed on the same value.
        index._projection = None


async def get_semantic_index(app_state) -> SemanticIndex:
    if not hasattr(app_state, "semantic_index"):
        app_state.semantic_index = SemanticIndex()
    return app_state.semantic_index
