.PHONY: dev build up down migrate test test-db lint typecheck check

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
