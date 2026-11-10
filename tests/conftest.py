import os
from urllib.parse import urlsplit

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from training_queue.api import create_app
from training_queue.config import Settings
from training_queue.db import make_database
from training_queue.transitions import Queue


@pytest.fixture
async def queue():
    url = os.environ.get(
        "TEST_DATABASE_URL", "postgresql+asyncpg://queue:queue@localhost:55432/queue_test"
    )
    if not urlsplit(url).path.endswith("_test"):
        pytest.fail("TEST_DATABASE_URL database name must end in _test (tests truncate it)")
    engine, sessions = make_database(url)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE job_effects, jobs"))
    try:
        yield Queue(sessions, Settings(database_url=url))
    finally:
        await engine.dispose()


@pytest.fixture
async def client(queue):
    async with AsyncClient(
        transport=ASGITransport(app=create_app(queue=queue)), base_url="http://test"
    ) as client:
        yield client
