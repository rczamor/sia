# The ingestion webhook

One generic inbound endpoint lets an automation platform — **Zapier, n8n, or
Make** — push content into Sia. Those platforms already have thousands of
connectors; they authenticate to the source, pull the data, and map it onto Sia's
payload. So Sia needs **no per-source integration code** — the automation platform
is the connector layer.

```
Google Drive ─┐
Slack ────────┼─→  Zapier / n8n / Make  ──POST──→  /api/ingest/webhook
Notion ───────┘     (the connector layer)            (one endpoint)
```

## Endpoint

```
POST /api/ingest/webhook
Header: X-Sia-Webhook-Token: <INGEST_WEBHOOK_SECRET>
Content-Type: application/json
```

Set `INGEST_WEBHOOK_SECRET` in the environment to enable it (empty → `503`). The
token is compared in constant time; a bad/missing token → `401`.

### Payload

| Field | Required | Notes |
|---|---|---|
| `title` | yes | human-readable title |
| `content` | no\* | the text to ingest (the platform already fetched it) |
| `url` | no\* | source URL — provenance, or the page to fetch when `content` is empty |
| `source` | no | provenance label, e.g. `zapier:gdrive`; stored as a note |
| `author` | no | original author |

\* Provide `content` **or** `url`. With `content`, the text is ingested directly
(the right mode for auth-gated sources whose URL Sia can't re-fetch). With only a
public `url`, it's queued for fetch + extract like `/api/ingest/url`.

Returns `202 { "status": "queued", "job_id": "...", "mode": "content" | "url" }`.

### Example

```bash
curl -X POST https://<your-sia-host>/api/ingest/webhook \
  -H "X-Sia-Webhook-Token: $INGEST_WEBHOOK_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"title": "Q3 planning doc",
       "content": "Full text of the doc…",
       "source": "zapier:gdrive",
       "author": "Riché"}'
```

## Trust & safety

Webhook intake is machine-fed, so it lands at the **untrusted** trust tier: it is
classified and quarantine-screened on the way in, and it cannot be consolidated
until it clears the human-reviewed merge gate (see
[threat-model.md](threat-model.md)). The endpoint authenticates with its own shared
secret (like the Slack capture route) rather than an owner session, so it never
exposes the owner credential to a third-party platform. Give each platform the same
secret, or rotate the secret to cut all of them off at once.

## Wiring it up

### Zapier
- **No-code:** add a **Webhooks by Zapier → POST** action, URL
  `https://<host>/api/ingest/webhook`, header
  `X-Sia-Webhook-Token: <secret>`, JSON body mapped from your trigger.
- **First-class action:** the CLI app in
  [`integrations/zapier/`](../integrations/zapier) adds a reusable **Ingest
  Content** action.

### n8n
- **No-code:** an **HTTP Request** node — `POST` to the endpoint, header auth with
  the token, JSON body from the previous node.
- **First-class node:** the community node in
  [`integrations/n8n/`](../integrations/n8n) (`n8n-nodes-sia`) adds a native **Sia**
  node.

### Make / anything else
Any tool that can send an authenticated HTTP POST works — there is nothing
Zapier/n8n-specific about the endpoint.
