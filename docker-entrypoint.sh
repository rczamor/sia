#!/usr/bin/env bash
# Preflight the database, apply migrations (engine only), then run the given
# command. A fresh `docker compose up` works end to end: the engine verifies the
# DB and extension privileges with one clear error if anything is off, migrates a
# blank database before serving, and only then starts. The worker sets
# SIA_SKIP_MIGRATE=1 and instead waits for the engine's migration to finish, so
# only one process migrates (no race).
set -euo pipefail

# Settings.trusted_proxy_ips is the documented knob; uvicorn reads the trust
# list from FORWARDED_ALLOW_IPS, which still wins when set explicitly.
if [ -n "${TRUSTED_PROXY_IPS:-}" ] && [ -z "${FORWARDED_ALLOW_IPS:-}" ]; then
  export FORWARDED_ALLOW_IPS="$TRUSTED_PROXY_IPS"
fi

if [ "${SIA_SKIP_MIGRATE:-0}" = "1" ]; then
  echo "Waiting for migrations to reach head before starting the worker..."
  python - <<'PY'
import asyncio, os, sys
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# The worker must not start until the engine has migrated to HEAD — alembic_version
# appears at the START of migration, so existence alone is not enough; compare the
# stamped revision to the head revision.
head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()

async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    for _ in range(180):
        try:
            async with engine.connect() as conn:
                current = await conn.scalar(text("SELECT version_num FROM alembic_version"))
                if current == head:
                    await engine.dispose()
                    return
        except Exception:
            pass
        await asyncio.sleep(1)
    print(f"Timed out waiting for migrations to reach head ({head})", file=sys.stderr)
    sys.exit(1)

asyncio.run(main())
PY
else
  echo "Running database preflight..."
  python scripts/preflight_db.py --wait 60
  echo "Applying database migrations..."
  alembic upgrade head
fi

exec "$@"
