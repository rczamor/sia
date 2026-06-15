# n8n-nodes-sia

An [n8n](https://n8n.io) community node that pushes content into **Sia**, a
Context Engine, through its generic ingestion webhook (`POST /api/ingest/webhook`).

Use any n8n trigger (Google Drive, Slack, Notion, RSS, a form, …), map the fields
onto the Sia node, and the content flows into Sia's data layer — classified,
quarantine-screened, and held at the untrusted tier until you clear it through the
review gate. No per-source code in Sia: **n8n is the connector layer.**

## Install

Community node (n8n ≥ 1.0): **Settings → Community Nodes → Install** →
`n8n-nodes-sia`.

Or build from source:

```bash
cd integrations/n8n
npm install
npm run build
# then load the dist/ output as a custom node (see n8n custom-node docs)
```

## Credentials — "Sia API"

| Field | Value |
|---|---|
| Base URL | your Sia host, e.g. `https://sia.example.com` (no trailing slash) |
| Webhook Token | the `INGEST_WEBHOOK_SECRET` configured on your Sia instance |

The token is sent as the `X-Sia-Webhook-Token` header on every request.

## Node — "Sia" → Ingest

| Field | Notes |
|---|---|
| Title | required |
| Content | the text to ingest; leave empty + set URL to have Sia fetch a public page |
| URL | source URL (provenance, or the page to fetch when Content is empty) |
| Source | provenance label, e.g. `n8n:gdrive` |
| Author | optional |

Returns `{ status: "queued", job_id, mode }`. See
[../../docs/ingestion-webhook.md](../../docs/ingestion-webhook.md) for the payload
contract.
