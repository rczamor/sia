.PHONY: dev build up down migrate seed test lint

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

seed:
	docker compose exec engine python scripts/seed_data.py

test:
	docker compose exec engine pytest

lint:
	docker compose exec engine ruff check app/
