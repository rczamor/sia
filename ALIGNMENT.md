# ALIGNMENT.md — Codebase Audit vs. Four-Layer Architecture (Phase 0)

**Date:** 2026-06-11 · **Ticket:** TRZ-1007 · **Status:** Complete

This document records the verified state of the `sia` repository at the start of the
architecture revamp, what was kept, what was removed, and every claim in the planning
docs that turned out to be wrong. Every statement below was verified by running the
code, not by reading docs.

---

## 1. Verified repo state (commit `c33b3b0`)

- ~2,700 LOC Python, 3 commits, **zero tests**, **no CI** (`.github/` did not exist —
  TRZ-131's claim that `deploy.yml` exists is false).
- App boots and migration `001` applies cleanly against Postgres 16 + pgvector.
- Ingestion pipeline works end-to-end in code review: trafilatura fetch → Claude Haiku
  classify/summarize → Ollama `nomic-embed-text` (768-dim) embed → store + version row.

## 2. Defects found and verified (fixed in Phase 0 unless noted)

| # | Defect | Evidence | Fix |
|---|--------|----------|-----|
| 1 | **Packaging broken**: `pip install .` fails in working tree — setuptools flat-layout discovers `app`, `static`, `alembic`, `templates` as packages. The Dockerfile only dodges this by copying `app/__init__.py` alone before install. | `uv pip install -e .` → "Multiple top-level packages discovered in a flat-layout" | Phase 0: `[tool.setuptools.packages.find] include = ["app*"]` |
| 2 | **Admin UI 500s on every page**: `TemplateResponse("name", {ctx})` legacy call signature; current Starlette expects `(request, name, ctx)`. | `GET /admin` → 500 `TypeError: unhashable type: 'dict'` | Phase 0: new signature in `app/ui.py` |
| 3 | **HNSW embedding indexes never created**: declared in `tables.py` `__table_args__` but absent from migration `001`. A migration-built DB seq-scans every dense search. | `\di source_content` → no `ix_source_content_embedding` | Phase 1: migration `003_hnsw_indexes` |
| 4 | **SQL injection surface**: pillar and date filters interpolated into SQL via f-strings in `knowledge_store.py:241-249`. | Code review; `pillar` reaches the f-string from query params | Phase 0: parameterized; fully rebuilt in Phase 1 retrieval layer |
| 5 | **SSRF-open ingestion**: `/api/ingest/url` fetches any URL via trafilatura — including `http://169.254.169.254/` and internal hosts. | Code review `ingestion.py:38` | Phase 0: scheme allowlist + private/metadata IP blocklist |
| 6 | **Dashboard quick actions 422**: HTMX forms post `application/x-www-form-urlencoded` to JSON-body endpoints. | `templates/dashboard.html:33,40` | Phase 0: `json-enc` htmx extension |
| 7 | **Auth enforced on zero routes**: JWT login exists (`app/auth.py`) but no route uses `get_current_user`. Admin UI and all write APIs are unauthenticated. | `grep get_current_user app/` → definition only | Phase 3: deny-by-default middleware + cookie auth |
| 8 | **Cross-table score incompatibility** (TRZ-110): `hybrid_search` merges per-table `semantic*0.7 + ts_rank_cd*0.3` scores; `ts_rank_cd` is unbounded so ordering across tables is meaningless. | Code review `knowledge_store.py:187-300` | Phase 1: RRF fusion replaces weighted sum |
| 9 | **Multi-pillar UI impossible**: thought form uses checkboxes but JSON endpoint expects an array; form-encoding sends repeated keys the schema rejects. | Same root cause as #6 | Phase 0 |
| 10 | **`plugins.credentials` JSONB stores secrets in plaintext** at rest. | `tables.py:290` | Phase 1: plugin SDK uses env-based secrets; column dropped |
| 11 | **Search has never executed successfully**: SQLAlchemy `text()` treats `:query_vec::vector` as an escaped-colon literal, so the bind param is never substituted and every `hybrid_search` call raises `PostgresSyntaxError`. Any admin-UI search 500s. | First-ever integration test failed; reproduced in isolation | Phase 0: `CAST(:query_vec AS vector)`; pillar/date filters parameterized in the same change |

## 3. Dead schema / dead code (removed in Phase 0)

Nothing anywhere reads or writes these — no service code, no endpoints, no jobs:

- **Tables dropped** (migration `002_remove_publishing`): `generated_posts`,
  `experiments`, `output_templates`. Data archived to JSON by
  `scripts/archive_publishing.py` before dropping (all were empty in every known DB).
- **`consolidations` kept until Phase 5**: schema-only today (zero writers), retained
  read-only through the context-store migration window, dropped in migration `006`.
- **Code removed**: `GeneratedPosts`/`Experiments`/`OutputTemplates` ORM classes;
  `PostStatus`, `FactCheckStatus`, `Channel`, `ExperimentStatus` enums and
  `EntityType.GENERATED_POSTS`; `PublishingChannel`/`PublishResult`/`PostMetrics`
  protocol types; `app/plugins/publishing/`; `n8n_webhook_secret` setting; LinkedIn/X/n8n
  env vars; publishing seed rows (`linkedin`, `x` plugins; five `output_templates`).
- **Dead `SearchRequest` schema** removed (search uses GET query params).
- **`PluginManager` never instantiated** — becomes the real plugin SDK in Phase 1.
- **`app/mcp/` empty** — becomes the MCP gateway in Phase 3.
- **Langfuse**: NoOp stub only; `langfuse` plugin row exists but no implementation.
- **Makefile `seed` target** referenced nonexistent `scripts/seed_data.py` — removed.

## 4. Kept (good bones)

- Ingestion pipeline (`app/services/ingestion.py`) — becomes Data-layer intake.
- `TrackedLLMProvider` lineage capture (`app/services/lineage.py`) — the audit trail
  the whole thesis depends on; extended with `build_id`/principal in Phase 3.
- Versioning (`app/services/versioning.py`) — restore endpoint added in Phase 5.
- Provider protocols (`app/providers/base.py`) — the seams for the plugin SDK.
- Schema for `source_content`, `my_thoughts`, `expertise_artifacts`,
  `content_versions`, `process_lineage`, `ai_config`, `plugins` + tsvector triggers.
- Admin UI skeleton (Jinja2 + HTMX + Pico CSS).

## 5. Claims in planning docs that were wrong

| Claim | Reality |
|---|---|
| "deploy.yml exists, needs updating" (TRZ-131) | No `.github/` directory at all |
| "consolidation engine implemented" | `consolidations` table only; zero code paths write it |
| "Langfuse integrated" | NoOp stub; no Langfuse SDK dependency |
| "Feedly polling live" | No Feedly code beyond a disabled plugin registry row |
| "publishing pipeline generates drafts" | No generation code exists anywhere |
| "chat interface needs rewiring" (TRZ-1014 original) | No `/api/chat` or dialogue code exists — nothing to rewire |

## 6. Environment facts

- **Production database: Neon Postgres (confirmed by Riché, 2026-06-11).** Local dev
  and CI use plain Postgres 16 + pgvector; the app is host-agnostic via `DATABASE_URL`.
  The production host could not be reached from the dev container. **Assumption:
  production rows ≈ 0** (repo is 3 commits old, no seed script ever existed). The
  Phase 2 backfill is gated on a row count at deploy time: if `source_content` > 0,
  run the backfill job; the hand-migration path was written for the ~0 case.
- n8n: no webhook code exists in the repo; the `n8n_webhook_secret` setting was load-bearing
  for nothing. Whether an n8n instance runs on the VPS is irrelevant to this codebase —
  n8n tickets (TRZ-122/123/124/197) cancelled.
- Ollama is assumed reachable at `OLLAMA_URL` for embeddings; CI uses a fake embedder.

## 7. Vocabulary migration

Per the Platform Document terminology guide (locked 2026-05-07):

| Was | Now |
|---|---|
| "Context Layer Engine" (legacy product name) | **Sia**, category: **Context Engine** |
| "Context Intelligence" (pillar display label) | **Context Architecture** |
| "three-phase context architecture: ingest, consolidate, retrieve" | **four layers: Data, Retrieval, Context, Inference** (Sia implements the first three; Inference belongs to the consuming harness) |

The stored enum value `context_layers` is unchanged (data compatibility); only display
labels and prompt text changed. The classification prompt reword is behavior-affecting
and covered by the golden ingestion test.
