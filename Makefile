.PHONY: dev build up down migrate test lint typecheck check

dev:
	docker compose up --build

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
