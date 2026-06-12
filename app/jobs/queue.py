"""Procrastinate job queue.

Jobs live in Postgres (the procrastinate_* tables, applied by migration 003), so a
killed worker or app restart loses nothing — queued jobs survive and are picked up
by the next worker. Run a worker with:

    procrastinate --app=app.jobs.queue.job_queue worker
"""

import procrastinate

from app.config import settings


def _psycopg_dsn(url: str) -> str:
    """Procrastinate uses psycopg; strip the SQLAlchemy asyncpg driver marker."""
    return url.replace("postgresql+asyncpg://", "postgresql://")


job_queue = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=_psycopg_dsn(settings.database_url)),
    import_paths=["app.jobs.tasks"],
)
