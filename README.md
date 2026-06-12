# Sia — an open-source Context Engine

Sia serves **decision-ready context to any AI agent harness** — Claude, ChatGPT,
Cursor, or anything that speaks MCP. It is the working implementation of the
[Context Architecture thesis](https://richezamor.com/thesis): *data is not context* —
context must be actively generated through five steps (curate, synthesize, consolidate,
prioritize, store) at a dedicated layer most AI systems skip entirely.

## The four layers

An AI system has four layers. Sia implements the first three; the fourth belongs to
whatever harness consumes it:

| Layer | Does | In Sia |
|---|---|---|
| **Data** | stores | Postgres (raw sources, thoughts, expertise, lineage, versions) |
| **Retrieval** | reaches | hybrid search: BM25 + dense vectors fused with RRF |
| **Context** | turns retrieval into meaning | the engine: consolidation clocks, a git-backed Markdown context store, a knowledge graph, goal-aware context builds |
| **Inference** | generates | **not Sia** — your agent harness, connected via MCP |

Sia is not a chat app. It is a connector you add to your harness; the harness asks
`sia_build_context(goal, budget)` and gets back a cited, scored, budget-shaped
context artifact built from consolidated knowledge — not raw retrieval chunks.

## Quick start

```bash
cp .env.example .env   # set DATABASE_URL, ANTHROPIC_API_KEY, OLLAMA_URL
make dev               # build + start the engine
make migrate           # apply database migrations
open http://localhost:8000/admin
```

Requirements: Postgres with [pgvector](https://github.com/pgvector/pgvector)
(Neon works out of the box), an [Ollama](https://ollama.com) instance with
`nomic-embed-text` for embeddings, and an LLM API key for internal context
operations (classification, consolidation, synthesis — Sia core never generates
end-user content).

## Stack

- **Backend:** Python / FastAPI
- **Database:** Postgres + pgvector (one datastore; the knowledge graph is plain tables)
- **Context store:** git-backed Markdown files (diffable, reviewable, portable)
- **Embeddings / LLM / observability:** pluggable providers (Ollama, Anthropic,
  OpenRouter, Langfuse, …)
- **Admin UI:** Jinja2 + HTMX + Pico CSS

## Project documents

- [`ALIGNMENT.md`](ALIGNMENT.md) — audit of the codebase against this architecture
- [`SECURITY.md`](SECURITY.md) — security policy and reporting
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — development setup and conventions
