"""Local embedding generation via fastembed (ONNX, CPU-only).

The model is loaded lazily on first use and kept as a module-level singleton:
it takes several seconds to initialize, so startup must not block on it. A
failed load is latched so a broken install degrades to exact-match search
instead of retrying a multi-hundred-MB download on every request.
"""
import asyncio
import logging
import os
import threading

import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

_model = None
_load_failed = False
_lock = threading.Lock()


def _get_model():
    global _model, _load_failed
    if _model is None and not _load_failed:
        with _lock:
            if _model is None and not _load_failed:
                try:
                    from fastembed import TextEmbedding

                    logger.info(
                        "Loading embedding model %s (cache: %s)",
                        settings.embedding_model,
                        settings.embedding_cache_dir,
                    )
                    os.makedirs(settings.embedding_cache_dir, exist_ok=True)
                    _model = TextEmbedding(
                        settings.embedding_model,
                        cache_dir=settings.embedding_cache_dir,
                    )
                except Exception as exc:
                    _load_failed = True
                    logger.warning(
                        "Embedding model %s failed to load; semantic search "
                        "disabled until restart: %s",
                        settings.embedding_model,
                        exc,
                    )
    return _model


def reset_model_cache():
    """Test hook: forget the singleton so patched settings take effect."""
    global _model, _load_failed
    with _lock:
        _model = None
        _load_failed = False


def build_embedding_text(title: str | None, description: str | None, tags: str | None) -> str:
    parts = [p.strip() for p in (title, description, tags) if p and p.strip()]
    return " ".join(parts)


def _embed_sync(texts: list[str]) -> list[list[float]] | None:
    model = _get_model()
    if model is None or not texts:
        return None
    vectors = [v.astype(np.float32).tolist() for v in model.embed(texts)]
    return vectors


async def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Embed a batch of texts. Returns None when the model is unavailable —
    callers treat that as "skip semantic features" rather than an error."""
    if not texts:
        return []
    return await asyncio.to_thread(_embed_sync, texts)


async def embed_bookmark(
    title: str | None, description: str | None, tags: str | None
) -> bytes | None:
    """Return the stored form of a bookmark's embedding (float32 BLOB)."""
    text = build_embedding_text(title, description, tags)
    if not text:
        return None
    vectors = await embed_texts([text])
    if not vectors:
        return None
    return np.asarray(vectors[0], dtype=np.float32).tobytes()


async def embed_query(query: str) -> list[float] | None:
    vectors = await embed_texts([query])
    if not vectors:
        return None
    return vectors[0]


async def warmup_embeddings() -> None:
    """Pre-load the model at startup so the first search doesn't pay for it."""
    try:
        await embed_texts(["warmup"])
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("Embedding warmup failed: %s", exc)
