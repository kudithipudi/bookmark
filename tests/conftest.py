import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.database import (
    get_db,
    SQL_CREATE_TABLE,
    SQL_CREATE_RATE_LIMIT_TABLE,
    SQL_CREATE_RATE_LIMIT_INDEX,
)
import aiosqlite


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
