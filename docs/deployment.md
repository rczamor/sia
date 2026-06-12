# Deploying Sia

## Single VPS (reference deployment)

Requirements: Docker + compose, a Postgres with pgvector (Neon recommended), an
Ollama instance with `nomic-embed-text`, a domain with TLS at your proxy.

```bash
git clone https://github.com/rczamor/sia && cd sia
cp .env.example .env        # fill in: DATABASE_URL (Neon), keys, JWT_SECRET, admin hash
docker compose up -d        # engine + worker
docker compose exec engine alembic upgrade head
```

No external Postgres? `docker compose --profile bundled-db up -d` and set
`DATABASE_URL=postgresql+asyncpg://sia:sia@db/sia` (change the password in compose).

Put a TLS-terminating proxy (Caddy/nginx/Traefik) in front of port 8000. Example
Caddyfile:

```
sia.example.com {
    reverse_proxy localhost:8000
}
```

Then tell Sia it's behind TLS — in `.env`:

```bash
FORCE_HTTPS=true              # Secure session cookie + HSTS, unconditionally
FORWARDED_ALLOW_IPS=<proxy-ip>  # which peer uvicorn trusts for X-Forwarded-* headers
```

`FORCE_HTTPS` is the safety net: without it, a proxy that isn't in
`FORWARDED_ALLOW_IPS` leaves uvicorn seeing plain http, and the session cookie
would be set without `Secure` and HSTS would never be sent. With the Caddyfile
above (proxy on the same host) `FORWARDED_ALLOW_IPS=172.17.0.1` (Docker bridge
gateway) is typical; verify with `docker network inspect bridge`.

Then connect your harnesses: see [connectors.md](connectors.md).

## Continuous deployment (GitHub Actions)

`.github/workflows/deploy.yml` builds the image and deploys over SSH on every push
to `main`, **only if** these repository secrets are configured (it skips cleanly
otherwise): `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_PATH`.

## Backups & restore

Two things hold all state; both must be backed up:

1. **Postgres** — nightly `pg_dump` (Neon also has point-in-time restore):
   ```bash
   pg_dump "$DATABASE_URL_SYNC" | gzip > sia-$(date +%F).sql.gz
   ```
2. **Context store** — set `CONTEXT_STORE_REMOTE` to a private git remote; the
   store pushes after every review merge. Manual: `git -C /srv/sia/context push`.

### Restore runbook
1. Restore the Postgres dump (or Neon PITR) into a fresh database.
2. Clone the context-store mirror to `CONTEXT_STORE_PATH`.
3. `alembic upgrade head` (no-op if the dump is current).
4. Start the engine; run `POST /api/context/consolidate/rem` (or wait for the
   daily clock) — the REM clock re-syncs `context_sections` and the graph from the
   store, so the Postgres index converges to the files even if the dump was stale.
5. Verify: `/admin/health` shows store composition; run a build in the inspector.

The drill above is the recovery property the architecture guarantees: **files are
canonical; every Postgres context table is rebuildable from the store**.

## Operational checklist

- [ ] `JWT_SECRET` is random and not the example value
- [ ] `FORCE_HTTPS=true` set; login response carries a `Secure` cookie and a
      `Strict-Transport-Security` header (check the browser dev tools)
- [ ] Admin password hash set; login works; `/admin` unreachable anonymously
- [ ] Per-consumer API keys created (never share the owner session)
- [ ] Slack alert webhook configured (consolidation failures page you)
- [ ] Backups verified by an actual restore, not by hope
