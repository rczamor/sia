# Sia — Context Layer Engine

Personal Knowledge Intelligence System demonstrating the three-phase context architecture: **ingest, consolidate, retrieve**.

## Quick Start

```bash
# Copy environment config
cp .env.example .env
# Edit .env with your Neon Postgres URL and Anthropic API key

# Start the engine
make dev

# Run database migrations
make migrate

# Open admin UI
open http://localhost:8000/admin
```

## Architecture

- **Backend:** Python FastAPI
- **Database:** Neon Postgres + pgvector
- **Embeddings:** Ollama (nomic-embed-text)
- **LLM:** Anthropic Claude API
- **Admin UI:** Jinja2 + HTMX + Pico CSS
