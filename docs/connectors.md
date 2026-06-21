# Connecting Sia to your agent harness

Sia is a context provider, not a chat app. You add it to whatever harness you
already use; the harness calls `sia_build_context` and reasons over what comes back.
One MCP server covers everything: `https://<your-sia-host>/mcp`.

## 1. Get an API key

Sign in to the admin UI and create a per-purpose principal (key is shown once):

```bash
curl -X POST https://<host>/api/principals \
  -H "Cookie: sia_session=<your session>" -H "Content-Type: application/json" \
  -d '{"purpose": "claude-desktop", "token_budget": 8000,
       "allowed_visibilities": ["public", "private"], "allow_fallback": true}'
```

Give every consumer its own key — usage is audited per principal in
`context_builds`, and you can rotate or revoke each independently.

## 2. Add the connector

### Claude (claude.ai, Desktop) — custom connector
Settings → Connectors → *Add custom connector*:
- URL: `https://<host>/mcp`
- Authentication: Bearer token → paste your `sia_...` key

### Claude Code
```bash
claude mcp add --transport http sia https://<host>/mcp \
  --header "Authorization: Bearer sia_..."
```

### ChatGPT — custom connector (MCP)
Settings → Connectors → *Add connector* → server URL `https://<host>/mcp`,
auth header `Authorization: Bearer sia_...`.

### Cursor
`.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "sia": {
      "url": "https://<host>/mcp",
      "headers": { "Authorization": "Bearer sia_..." }
    }
  }
}
```

### Anything else (REST parity)
Every MCP tool has a REST equivalent; the flagship:
```bash
curl -X POST https://<host>/api/context/build \
  -H "Authorization: Bearer sia_..." -H "Content-Type: application/json" \
  -d '{"goal": "prep for the pricing decision", "format": "markdown"}'
```

## 3. The tools

| Tool | What it does |
|---|---|
| `sia_build_context` | **Start here.** Cited, scored, budget-shaped context for a goal: consolidated topics, relevant skills (progressively disclosed), cautions from the tensions ledger, labeled raw fallback when permitted. |
| `sia_search` | Targeted hybrid search (BM25 + dense, RRF) over raw data. |
| `sia_list_topics` / `sia_read_topic` | Browse/read consolidated topic files. |
| `sia_list_skills` / `sia_read_skill` | Procedural knowledge; read only when the trigger matches. |
| `sia_add_thought` / `sia_add_source` | Write back into the data layer (not visitors). |
| `sia_flag` | Tell Sia whether a build was useful — feeds consolidation priorities. |
| `sia_record_bypass` | Report that you used a source *outside* Sia for a goal — feeds the bypass ledger so coverage gaps get found and closed. |
| `sia_resolve_source` | Resolve a `[source:<uuid>]` citation to its record. |
| `sia_consolidate` | Owner-only: trigger a clock manually. |

## Making Sia the first stop

Adding the connector makes Sia *available*; it doesn't make the harness *start*
there. See [default-context-source.md](default-context-source.md) for the strategy
(absorb competing sources, enforce at the harness, measure bypass) and the drop-in
enforcement artifacts in [`harness/`](../harness) for Claude Code, Cursor, and
generic system prompts.

## Principals at a glance

| | visibility | budget | raw fallback | writes |
|---|---|---|---|---|
| owner | public+private | 12k | yes | yes |
| agent-* | per grant | per grant | per grant | yes |
| visitor (no key) | public only | 2.5k | **no** | no |
