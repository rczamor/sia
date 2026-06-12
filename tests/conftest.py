import os

# Environment must be set before any app module is imported (app.config reads it
# at import time). External values (CI) win; these are local-dev fallbacks.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@127.0.0.1/sia_test"
)
os.environ.setdefault("JWT_SECRET", "test-only-secret")

import tempfile  # noqa: E402

os.environ.setdefault("CONTEXT_STORE_PATH", tempfile.mkdtemp(prefix="sia-store-"))
os.environ.setdefault("ADMIN_EMAIL", "admin@test.local")
# bcrypt hash of "test-password" (test-only credential)
os.environ.setdefault(
    "ADMIN_PASSWORD_HASH",
    "$2b$12$7w6eIj5ZhWohExwJsqGoVuKIVdPsllGYRASpf23KadBy9BVhMqLDC",
)

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    """Apply the full migration chain once per test session, with a clear preflight
    error when the test database or the pgvector extension is missing."""
    import psycopg

    dsn = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    try:
        with psycopg.connect(dsn) as conn:
            has_vector = conn.execute(
                "SELECT 1 FROM pg_available_extensions WHERE name = 'vector'"
            ).fetchone()
            if not has_vector:
                pytest.exit(
                    "pgvector is not available in this Postgres. Install the extension "
                    "(e.g. `apt-get install postgresql-16-pgvector`) or use the "
                    "pgvector/pgvector image, then create the test DB: `make test-db`.",
                    returncode=1,
                )
    except psycopg.OperationalError as exc:
        pytest.exit(
            f"Cannot connect to the test database ({exc}). Create it with "
            "`make test-db` and set DATABASE_URL to point at it.",
            returncode=1,
        )
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
                "content_versions, process_lineage, "
                "context_sections, consolidation_runs, entities, context_edges, "
                "context_builds CASCADE"
            )
        )
        # seeded owner/visitor principals stay; per-test agents go
        await session.execute(text("DELETE FROM principals WHERE kind = 'agent'"))
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
async def store(tmp_path, monkeypatch):
    """Fresh scaffolded context store per test; runtime picks it up via settings."""
    from app.config import settings
    from app.context.store.gitstore import GitContextStore
    from app.context.store.layout import scaffold_store

    root = tmp_path / "context"
    monkeypatch.setattr(settings, "context_store_path", str(root))
    git_store = GitContextStore(str(root))
    await scaffold_store(git_store)
    return git_store


@pytest.fixture
async def fake_runtime(store, monkeypatch):
    """A real Runtime wired to the test store and a deterministic embedder, installed
    as the module-global so every `get_runtime()` call site sees it."""
    from app import runtime as runtime_module
    from app.models.enums import PluginCategory
    from app.plugins.base import PluginHealth, PluginManager
    from tests.fakes import HashingEmbedder

    class FakeEmbeddingsPlugin:
        plugin_id = "ollama"
        category = PluginCategory.EMBEDDINGS
        provider = HashingEmbedder()

        async def initialize(self, config):
            pass

        async def health_check(self):
            return PluginHealth(healthy=True)

        async def shutdown(self):
            pass

    manager = PluginManager()
    manager.register(FakeEmbeddingsPlugin())
    runtime = runtime_module.Runtime(manager, {})
    runtime.context_store = store
    monkeypatch.setattr(runtime_module, "_runtime", runtime)
    return runtime


@pytest.fixture
async def client():
    """Owner-authenticated client (session cookie), as the admin browser would be."""
    from app.auth import SESSION_COOKIE, create_token
    from app.config import settings
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={SESSION_COOKIE: create_token(settings.admin_email)},
    ) as c:
        yield c


@pytest.fixture
async def anon_client():
    """Unauthenticated client — sees only public surface."""
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
