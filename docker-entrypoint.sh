#!/usr/bin/env bash
# Wait for Postgres, apply migrations (engine only), then run the given command.
# A fresh `docker compose up` works end to end: the engine migrates a blank
# database before serving, so users never hit "relation does not exist" on first
# boot. The worker sets SIA_SKIP_MIGRATE=1 and instead waits for the engine's
# migration to finish, so only one process migrates (no race).
set -euo pipefail

python - <<'PY'
import os, socket, sys, time
from urllib.parse import urlparse

url = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
parsed = urlparse(url)
host, port = parsed.hostname or "localhost", parsed.port or 5432

for _ in range(60):
    try:
        with socket.create_connection((host, port), timeout=2):
            break
    except OSError:
        time.sleep(1)
else:
    print(f"Postgres at {host}:{port} not reachable after 60s", file=sys.stderr)
    sys.exit(1)
PY

if [ "${SIA_SKIP_MIGRATE:-0}" = "1" ]; then
  echo "Waiting for migrations to be applied by the engine..."
  python - <<'PY'
import asyncio, os, sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    for _ in range(120):
        try:
            async with engine.connect() as conn:
                ok = await conn.scalar(text("SELECT to_regclass('public.alembic_version')"))
                if ok:
                    await engine.dispose()
                    return
        except Exception:
            pass
        await asyncio.sleep(1)
    print("Timed out waiting for migrations", file=sys.stderr)
    sys.exit(1)

asyncio.run(main())
PY
else
  echo "Applying database migrations..."
  alembic upgrade head
fi

exec "$@"
