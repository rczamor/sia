import os

# Environment must be set before any app module is imported (app.config reads it
# at import time). External values (CI) win; these are local-dev fallbacks.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@127.0.0.1/sia_test"
)
os.environ.setdefault("JWT_SECRET", "test-only-secret")

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    """Apply the full migration chain once per test session."""
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture(autouse=True)
async def clean_tables(migrated_database):
    """Each test starts from empty data tables (config/seed rows are preserved).

    The engine pool is disposed at teardown because pytest-asyncio gives every test
    its own event loop, and asyncpg connections cannot cross loops.
    """
    from app.database import async_session, engine

    async with async_session() as session:
        await session.execute(
            text(
                "TRUNCATE source_content, my_thoughts, expertise_artifacts, "
                "consolidations, content_versions, process_lineage CASCADE"
            )
        )
        await session.commit()
    yield
    from app.runtime import reset_runtime_for_tests

    reset_runtime_for_tests()
    await engine.dispose()


@pytest.fixture
async def db_session():
    from app.database import async_session

    async with async_session() as session:
        yield session


@pytest.fixture
async def client():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
