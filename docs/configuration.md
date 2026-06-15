# Configuration reference

All secrets and deployment config come from environment variables (`.env` locally;
your orchestrator's secret store in production). Behavioral tuning lives in the
`ai_config` table (editable via `PUT /api/config/{key}`). The database stores **no
secrets**.

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | yes | — | Postgres + pgvector, `postgresql+asyncpg://…` (Neon works) |
| `ANTHROPIC_API_KEY` | one LLM key | — | LLM for internal context ops |
| `OPENROUTER_API_KEY` | one LLM key | — | Alternative LLM provider (any model, one key) |
| `OPENROUTER_BASE_URL` | no | openrouter.ai | OpenAI-compatible endpoint override |
| `OLLAMA_URL` | yes | host.docker.internal:11434 | Embeddings (`nomic-embed-text`) |
| `JWT_SECRET` | yes | — | Session signing — `openssl rand -hex 32` |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD_HASH` | yes | — | Admin login (bcrypt hash) |
| `CONTEXT_STORE_PATH` | no | /srv/sia/context | Git-backed store location |
| `CONTEXT_STORE_REMOTE` | no | — | Optional push mirror (e.g. a private GitHub repo) |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` | no | — | LLM-ops tracing |
| `FEEDLY_ACCESS_TOKEN` / `FEEDLY_BOARD_ID` | no | — | Feed polling |
| `SLACK_WEBHOOK_SECRET` | no | — | Inbound Slack capture auth |
| `SLACK_ALERT_WEBHOOK_URL` | no | — | Outbound failure/zero-work alerts |
| `CORS_ORIGINS` | no | (none) | Browser origins allowed to call the API |
| `CSP_HEADER` | no | built-in | Override the admin Content-Security-Policy (default is `default-src 'self'`; all assets are vendored) |
| `PUBLIC_BASE_URL` | no | — | Canonical external URL (e.g. `https://sia.example.com`); referenced by connector guides |
| `OWNER_TIMEZONE` | no | UTC | IANA timezone (e.g. `America/Los_Angeles`) for the session-orientation block at the top of every build. Unknown names fall back to UTC |
| `OWNER_LOCATION` | no | — | Free-text location shown in the orientation block; served only to private-trusted principals. Omitted if blank |
| `SESSION_COOKIE_SECURE` | no | **true** | Secure flag on the session cookie. Disable only for plain-http dev on a non-localhost host |
| `HSTS_ENABLED` | no | **true** | Send `Strict-Transport-Security`. Disable only for plain-http dev |
| `HSTS_MAX_AGE` | no | 63072000 | HSTS max-age in seconds (two years) |
| `TRUSTED_PROXY_IPS` | no | — | Peer IPs trusted for `X-Forwarded-*`; exported to uvicorn as `FORWARDED_ALLOW_IPS` by the entrypoint |
| `FORWARDED_ALLOW_IPS` | no | 127.0.0.1 | uvicorn-native override of the same trust list (takes precedence) |
| `JWT_EXPIRY_HOURS` | no | 24 | Session lifetime |
| `SIA_SKIP_MIGRATE` | no | 0 | Set by the worker container so only the engine runs migrations |

## ai_config keys

| Key | Shape | Controls |
|---|---|---|
| `llm_default` | `{provider, model, temperature, max_tokens}` | Fallback for any LLM operation |
| `llm_classification` | same | Ingestion classify/summarize |
| `llm_consolidation` | same | All three clocks |
| `retrieval` | `{rrf_k, candidates_per_table, min_similarity}` | Hybrid search fusion; `min_similarity` is the dense-side cosine floor (default 0.1, tune per embedding model) |
| `embedding` | `{provider, model, dimensions}` | Embedding selection |

`provider` is a plugin id (`anthropic`, `openrouter`, or any third-party LLM plugin).
Switching providers is a config change — no code, no restart of anything but the app.

## Plugins table

`plugins.enabled` + `plugins.config` (non-secret JSON) control which entry-point
plugins initialize at startup. Credentials always come from the environment.

## Pillars

The three knowledge pillars (`context_layers`, `product_mgmt`, `leadership`) are
currently defined in `app/models/enums.py` and the classification prompt
(`app/prompts/source_analyst.py`) — customize at fork time. Runtime-configurable
pillars are on the roadmap.
