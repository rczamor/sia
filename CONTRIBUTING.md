# Contributing to Sia

## Development setup

```bash
# Python 3.12+, Postgres 16+ with pgvector
uv venv --python 3.12 .venv
uv pip install -p .venv -e ".[dev]"
createdb sia && psql -d sia -c "CREATE EXTENSION vector;"
export DATABASE_URL=postgresql+asyncpg://user:pass@127.0.0.1/sia
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload
```

Or with Docker: `make dev && make migrate`.

## Quality gates (CI enforces all of these)

```bash
.venv/bin/ruff check app/ tests/        # lint
.venv/bin/pytest                        # tests (need DATABASE_URL pointing at a pgvector Postgres)
.venv/bin/lint-imports                  # layer contract: gateway → context → retrieval → data
```

## Architecture rules

- Four layers: **Data** (stores), **Retrieval** (reaches), **Context** (turns
  retrieval into meaning), **Inference** (external harnesses — not in this repo).
  Imports flow downward only; the import-linter contract is the source of truth.
- The Postgres schema changes only through Alembic migrations; ORM models in
  `app/models/tables.py` must match the migration chain exactly.
- No secrets in code, config defaults, or the database — environment variables only.
- LLM calls go through `TrackedLLMProvider` so lineage is captured; never call a
  provider SDK directly from service code.

## Pull requests

- Keep PRs scoped to one concern; include tests for behavior changes.
- CI must be green (lint, tests, import contract, secret scan, dependency audit).
