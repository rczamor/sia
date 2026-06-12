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
cp .env.example .env   # set DATABASE_URL, an LLM key, OLLAMA_URL, JWT_SECRET, admin hash
make dev               # engine + worker
make migrate           # apply database migrations
open http://localhost:8000/admin
```

No Postgres of your own? `docker compose --profile bundled-db up -d` bundles one.

Requirements: Postgres with [pgvector](https://github.com/pgvector/pgvector)
(Neon works out of the box), an [Ollama](https://ollama.com) instance with
`nomic-embed-text` for embeddings, and an LLM API key (Anthropic or OpenRouter)
for internal context operations (classification, consolidation, synthesis — Sia
core never generates end-user content).

Then connect a harness — Claude, ChatGPT, Cursor, anything MCP — in two minutes:
[docs/connectors.md](docs/connectors.md).

## How it works

- **Intake** (URLs, Feedly, Slack capture) is SSRF-guarded, classified, embedded,
  and trust-tiered; suspicious content is quarantined before it can ever be
  consolidated.
- **Three consolidation clocks** turn raw intake into a git-backed Markdown store
  of topic files with cited claims: light (post-ingest matching), REM (daily
  re-gisting, contradiction detection, citation-use priorities), deep (weekly
  entity linking, pruning, skill synthesis). Anything untrusted-derived merges
  only through a human-reviewed diff.
- **A knowledge graph in plain Postgres** (typed edges + recursive CTEs) links
  topics, skills, entities, and sources; the admin graph view overlays freshness
  and citation-use on the structure.
- **The ContextBuilder** assembles cited, scored, budget-shaped artifacts per
  principal (owner / per-purpose agents / anonymous visitors), with skills
  progressively disclosed and raw retrieval only as a labeled fallback.
- **Everything is measured**: every build gets a context_score, every model call
  is in the lineage ledger, /admin/health shows fallback rate and cost per
  decision, and a golden-fixture regression suite guards consolidation quality.

## Stack

- **Backend:** Python / FastAPI
- **Database:** Postgres + pgvector (one datastore; the knowledge graph is plain tables)
- **Context store:** git-backed Markdown files (diffable, reviewable, portable)
- **Embeddings / LLM / observability:** pluggable providers (Ollama, Anthropic,
  OpenRouter, Langfuse, …)
- **Admin UI:** Jinja2 + HTMX + Pico CSS

## Documentation

- [docs/connectors.md](docs/connectors.md) — add Sia to Claude / ChatGPT / Cursor / REST
- [docs/configuration.md](docs/configuration.md) — every env var and ai_config key
- [docs/deployment.md](docs/deployment.md) — VPS deploy, backups, restore runbook
- [docs/plugins.md](docs/plugins.md) — write an LLM/embeddings/ingestion plugin
- [docs/threat-model.md](docs/threat-model.md) — memory poisoning and what stops it
- [`ALIGNMENT.md`](ALIGNMENT.md) — audit of the original codebase against this architecture
- [`SECURITY.md`](SECURITY.md) — security policy and reporting
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — development setup and conventions
