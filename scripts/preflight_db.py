"""Database preflight: fail fast, with instructions, before migrations run.

Reports, in order:
  1. database reachable (waits up to --wait seconds for it to accept connections),
  2. pgvector available on the server,
  3. vector installed or creatable by this role,
  4. uuid-ossp installed or creatable by this role.

Exit 0 means `alembic upgrade head` is safe to run. Exit 1 means one clear,
actionable error — instead of a privilege failure halfway through a migration.
docker-entrypoint.sh runs this before migrating; run it by hand when pointing
Sia at a managed database (Neon, RDS, Cloud SQL, ...).
"""

import argparse
import asyncio
import os
import sys
import time

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine

REQUIRED_EXTENSIONS = ("vector", "uuid-ossp")


def fail(message: str) -> None:
    print(f"\npreflight FAILED: {message}", file=sys.stderr)
    sys.exit(1)


async def wait_for_database(engine, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            print("database reachable:        yes")
            return
        except (OperationalError, OSError) as exc:
            # Transient: server not accepting connections yet / network — retry.
            last_error = exc
            await asyncio.sleep(1)
        except Exception as exc:
            # Auth failure, missing database, malformed URL: waiting won't fix it,
            # so fail immediately with a clean message. Report only the exception
            # type (asyncpg/SQLAlchemy keep the password out of these, but the type
            # alone is leak-proof and points at the right knob).
            fail(
                f"could not connect to the database ({type(exc).__name__}). Check "
                "DATABASE_URL — credentials, host, and database name."
            )
    fail(
        f"database not reachable after {timeout}s ({type(last_error).__name__}). "
        "Check DATABASE_URL and that Postgres is running."
    )


async def check_extension(engine, name: str) -> None:
    async with engine.connect() as conn:
        installed = await conn.scalar(
            text("SELECT 1 FROM pg_extension WHERE extname = :name"), {"name": name}
        )
        if installed:
            print(f"{name + ' installed:':<27}yes")
            return

        available = await conn.scalar(
            text("SELECT 1 FROM pg_available_extensions WHERE name = :name"),
            {"name": name},
        )
        if not available:
            fail(
                f"the '{name}' extension is not available on this Postgres server. "
                "Install it (pgvector: `apt-get install postgresql-16-pgvector`, or "
                "use the pgvector/pgvector image; managed Postgres: enable it in the "
                "provider console), then re-run."
            )

    # Available but not installed: prove this role can create it, without leaving
    # state behind — CREATE inside a transaction we roll back.
    async with engine.connect() as conn:
        try:
            await conn.execute(text(f'CREATE EXTENSION IF NOT EXISTS "{name}"'))
            await conn.rollback()
            print(f"{name + ' creatable:':<27}yes (will be created by migration 001)")
        except ProgrammingError:
            fail(
                f"the '{name}' extension is available but this role may not create "
                f'it. Install it once as a database owner/admin — CREATE EXTENSION "'
                f'{name}"; — then rerun migrations.'
            )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wait", type=int, default=0, help="seconds to wait for the database (default 0)"
    )
    args = parser.parse_args()

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        fail("DATABASE_URL is not set.")

    engine = create_async_engine(url)
    try:
        await wait_for_database(engine, max(args.wait, 1))
        for name in REQUIRED_EXTENSIONS:
            await check_extension(engine, name)
    finally:
        await engine.dispose()
    print("preflight OK — safe to run `alembic upgrade head`")


if __name__ == "__main__":
    asyncio.run(main())
