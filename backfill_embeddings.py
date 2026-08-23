"""Compute embeddings for bookmarks that don't have one yet.

Run after upgrading an existing deployment (or after swapping
EMBEDDING_MODEL) so semantic search covers the whole library:

    ./venv/bin/python backfill_embeddings.py [--force]

Without --force, only rows with a NULL embedding are processed.
"""
import argparse
import asyncio

import numpy as np

from app.config import settings
from app.db import init_db, get_db
from app.services.embeddings import build_embedding_text, embed_texts

BATCH_SIZE = 64


async def backfill(force: bool = False):
    await init_db()
    db = await get_db()

    where = "" if force else " WHERE embedding IS NULL"
    cursor = await db.execute(f"SELECT id, title, description, tags FROM bookmarks{where}")
    rows = await cursor.fetchall()
    if not rows:
        print("All bookmarks already have embeddings.")
        await db.close()
        return

    print(f"Embedding {len(rows)} bookmarks with {settings.embedding_model}...")
    done = 0
    for offset in range(0, len(rows), BATCH_SIZE):
        batch = rows[offset : offset + BATCH_SIZE]
        texts = [
            build_embedding_text(r["title"], r["description"], r["tags"]) or r["url"]
            for r in batch
        ]
        vectors = await embed_texts(texts)
        if not vectors:
            print("Embedding model unavailable — nothing written. Install fastembed and retry.")
            break
        for row, vector in zip(batch, vectors):
            blob = np.asarray(vector, dtype=np.float32).tobytes()
            await db.execute(
                "UPDATE bookmarks SET embedding = ? WHERE id = ?", (blob, row["id"])
            )
        await db.commit()
        done += len(batch)
        print(f"  {done}/{len(rows)}")

    await db.close()
    print(f"Done: {done} bookmarks embedded.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="recompute embeddings even if present"
    )
    asyncio.run(backfill(parser.parse_args().force))
