# Sia — Zapier integration

A [Zapier CLI](https://platform.zapier.com/cli_docs/docs) app that pushes content
into **Sia**, a Context Engine, through its generic ingestion webhook
(`POST /api/ingest/webhook`).

Pair any of Zapier's thousands of triggers (Google Drive, Slack, Notion, Gmail,
forms, …) with the **Ingest Content** action and the data flows into Sia's data
layer — classified, quarantine-screened, and held at the untrusted tier until you
clear it through the review gate. No per-source code in Sia: **Zapier is the
connector layer.**

## Develop / deploy

```bash
cd integrations/zapier
npm install
npm install -g zapier-platform-cli
zapier login
zapier register "Sia"   # first time only
zapier push
```

Then add the integration to a Zap, authenticate with your Sia **Base URL** and
**Webhook Token** (`INGEST_WEBHOOK_SECRET`), and map your trigger's fields onto the
Ingest action.

## Action — Ingest Content

| Field | Notes |
|---|---|
| Title | required |
| Content | text to ingest; leave empty + set URL to have Sia fetch a public page |
| URL | source URL (provenance, or page to fetch when Content is empty) |
| Source | provenance label, e.g. `zapier:gdrive` (defaults to `zapier`) |
| Author | optional |

Returns `{ status: "queued", job_id, mode }`. See
[../../docs/ingestion-webhook.md](../../docs/ingestion-webhook.md) for the payload
contract.

## No-code alternative

You don't need this app to use Sia from Zapier — the built-in **Webhooks by
Zapier → POST** action works too. Point it at
`https://<your-sia-host>/api/ingest/webhook`, add header
`X-Sia-Webhook-Token: <secret>`, and send the JSON payload. This app just makes it
a first-class, reusable action.
