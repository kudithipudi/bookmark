"""Download and cache local favicons for bookmarks that don't have one yet.

Run once after upgrading to local favicon storage, or anytime to retry
bookmarks whose favicon fetch previously failed:

    ./venv/bin/python backfill_favicons.py [--force]

Without --force, only rows with no local favicon (NULL, empty, or still a
remote URL from before this feature shipped) are processed.
"""
import argparse
import asyncio

from app.db import init_db, get_db
from app.scraper import fetch_metadata
from app.services.favicon import save_favicon

BATCH_SIZE = 20


def _is_local(favicon: str | None) -> bool:
    return bool(favicon) and favicon.startswith("/favicons/")


async def backfill(force: bool = False):
    await init_db()
    db = await get_db()

    cursor = await db.execute("SELECT id, url, favicon FROM bookmarks")
    rows = await cursor.fetchall()
    if not force:
        rows = [r for r in rows if not _is_local(r["favicon"])]
    if not rows:
        print("All bookmarks already have a local favicon.")
        await db.close()
        return

    print(f"Backfilling favicons for {len(rows)} bookmarks...")
    done = 0
    failed = 0
    for row in rows:
        # A remote favicon URL scraped before this feature shipped can be
        # downloaded directly; otherwise (missing, or already a local path
        # under --force) re-scrape the page to find one.
        favicon_url = row["favicon"] if row["favicon"] and not _is_local(row["favicon"]) else None
        if not favicon_url:
            metadata = await fetch_metadata(row["url"])
            favicon_url = metadata.get("favicon")

        local_path = await save_favicon(row["url"], favicon_url)
        # Always write the result, even on failure: a row that still has a
        # pre-migration remote URL must be cleared to NULL, or the frontend
        # keeps hitting the original site directly on every page load.
        await db.execute(
            "UPDATE bookmarks SET favicon = ? WHERE id = ?", (local_path, row["id"])
        )
        if local_path:
            done += 1
        else:
            failed += 1

        if (done + failed) % BATCH_SIZE == 0:
            await db.commit()
        print(f"  {done + failed}/{len(rows)} (ok={done}, failed={failed})")

    await db.commit()
    await db.close()
    print(f"Done: {done} favicons saved, {failed} failed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="re-download favicons even if already local"
    )
    asyncio.run(backfill(parser.parse_args().force))
