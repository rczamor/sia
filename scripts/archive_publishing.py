"""One-time archive of publishing-era tables before migration 002 drops them.

Writes a JSON snapshot of generated_posts, experiments, and output_templates to a
directory OUTSIDE the repo (default: ~/sia-archives/). Run against the production
database before deploying migration 002:

    DATABASE_URL=postgresql+asyncpg://... python scripts/archive_publishing.py
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

TABLES = ["generated_posts", "experiments", "output_templates"]
PLUGIN_ROWS = ("linkedin", "x")


def _serialize(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return value
    return str(value)


async def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 1

    out_dir = Path(os.environ.get("ARCHIVE_DIR", Path.home() / "sia-archives"))
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"publishing-archive-{stamp}.json"

    engine = create_async_engine(database_url)
    archive: dict[str, list[dict]] = {}
    try:
        async with engine.connect() as conn:
            for table in TABLES:
                exists = await conn.execute(
                    text("SELECT to_regclass(:name)"), {"name": f"public.{table}"}
                )
                if exists.scalar() is None:
                    print(f"  {table}: does not exist, skipping")
                    archive[table] = []
                    continue
                # B608: table iterates the hardcoded TABLES tuple, not user input
                rows = await conn.execute(text(f"SELECT * FROM {table}"))  # nosec B608
                archive[table] = [
                    {k: _serialize(v) for k, v in row.items()} for row in rows.mappings()
                ]
                print(f"  {table}: {len(archive[table])} rows archived")
            plugin_rows = await conn.execute(
                text("SELECT * FROM plugins WHERE id = ANY(:ids)"),
                {"ids": list(PLUGIN_ROWS)},
            )
            archive["plugins"] = [
                {k: _serialize(v) for k, v in row.items()} for row in plugin_rows.mappings()
            ]
    finally:
        await engine.dispose()

    out_path.write_text(json.dumps(archive, indent=2))
    print(f"Archive written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
