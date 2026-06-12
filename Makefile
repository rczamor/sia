.PHONY: dev build up down migrate test test-db lint typecheck check lock

# Regenerate the dependency lockfile after editing pyproject.toml (needs uv:
# https://docs.astral.sh/uv/). Docker and CI install with `-c constraints.txt`.
lock:
	uv pip compile pyproject.toml --extra dev -o constraints.txt

dev:
	docker compose up --build

# Create the local test database with the pgvector extension. Requires a Postgres
# superuser (PGUSER/PGHOST/... from the environment). Managed Postgres (Neon) has
# the extension pre-enabled; point DATABASE_URL at a scratch DB there instead.
test-db:
	createdb sia_test 2>/dev/null || true
	psql -d sia_test -c "CREATE EXTENSION IF NOT EXISTS vector;"

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

migrate:
	docker compose exec engine alembic upgrade head

test:
	docker compose exec engine pytest

lint:
	docker compose exec engine ruff check app/ tests/

check: lint test
