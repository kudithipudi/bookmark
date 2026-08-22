import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.db import (
    get_db,
    SQL_CREATE_TABLE,
    SQL_CREATE_RATE_LIMIT_TABLE,
    SQL_CREATE_RATE_LIMIT_INDEX,
)
from app.config import settings
import aiosqlite


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch):
    # Settings loads the real .env; never let tests hit OpenRouter or gate
    # deletes on the production password.
    monkeypatch.setattr(settings, "openrouter_api_key", None)
    monkeypatch.setattr(settings, "delete_password", None)
    monkeypatch.setattr(settings, "rate_limit_per_minute", 20)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)


@pytest_asyncio.fixture
async def db():
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute(SQL_CREATE_TABLE)
    await conn.execute(SQL_CREATE_RATE_LIMIT_TABLE)
    await conn.execute(SQL_CREATE_RATE_LIMIT_INDEX)
    await conn.commit()
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def client(db):
    from app.main import app

    async def override_get_db():
        return db

    app.state.db = db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
