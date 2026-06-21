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

Sia is HTTPS-safe out of the box: the session cookie is always `Secure` and
HSTS is always sent (`SESSION_COOKIE_SECURE` / `HSTS_ENABLED`, both default
true) — nothing depends on whether the proxy forwards `X-Forwarded-Proto`.
Optionally set in `.env`:

```bash
PUBLIC_BASE_URL=https://sia.example.com  # canonical external URL
TRUSTED_PROXY_IPS=<proxy-ip>   # peers uvicorn trusts for X-Forwarded-* headers
```

**Scope the header trust carefully.** Whoever matches `TRUSTED_PROXY_IPS`
(exported to uvicorn as `FORWARDED_ALLOW_IPS`) can set `X-Forwarded-For` —
which keys the login/visitor rate limits — and `X-Forwarded-Proto`. With a
same-host proxy reaching the loopback-published port, connections arrive from
the Docker bridge gateway (often `172.17.0.1`) — an address **shared by every
process on the host**, not unique to your proxy. That is acceptable on a
single-purpose VPS (the compose file publishes the engine on `127.0.0.1` only,
so nothing off-host reaches it directly), but on a shared host run the proxy
as a container on the compose network and trust that container's IP instead.
Cookie/HSTS decisions never depend on the spoofable scheme either way.

Then connect your harnesses: see [connectors.md](connectors.md).

## Database requirements & privileges

Sia needs Postgres with the `vector` (pgvector) and `uuid-ossp` extensions. The
entrypoint runs `python scripts/preflight_db.py --wait 60` before migrating; it
reports each requirement and fails with **one** actionable error instead of a
privilege failure mid-migration:

- database reachable,
- `vector` available on the server,
- `vector` installed — or creatable by the app role,
- `uuid-ossp` installed — or creatable by the app role.

Migration 001 only runs `CREATE EXTENSION` when an extension isn't installed
yet, so the app role needs **no** special privileges when the extensions are
pre-enabled. If they aren't, install them once as a database owner/admin —
`CREATE EXTENSION vector; CREATE EXTENSION "uuid-ossp";` — then rerun
migrations.

### Managed Postgres checklist (Neon, RDS, Cloud SQL, ...)

- [ ] pgvector enabled (Neon: pre-available; RDS/Cloud SQL: supported versions)
- [ ] Extensions installed by an admin role, or the app role may create them
- [ ] `DATABASE_URL=postgresql+asyncpg://...` points at the database
- [ ] `python scripts/preflight_db.py` prints `preflight OK`
- [ ] `alembic upgrade head` (or just start the engine — the entrypoint migrates)

### Local test DB checklist

- [ ] Postgres running locally with the pgvector package installed
      (`apt-get install postgresql-16-pgvector`, or the `pgvector/pgvector` image)
- [ ] `make test-db` — creates `sia_test` and installs the extension (needs a
      superuser; on a managed DB, point `DATABASE_URL` at a scratch database
      with the extension pre-enabled instead)
- [ ] `pytest` — the conftest preflight will tell you in one line if the DB or
      extension is missing

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
   Bootstrap or verify the separate repo with:
   ```bash
   python scripts/init_context_store.py --remote "$CONTEXT_STORE_REMOTE"
   ```

### Legacy consolidation backfill

If upgrading a database that still contains the retired `consolidations` table,
backfill it into topic files before applying the table-drop migration:

```bash
python scripts/backfill_consolidations.py
```

If the table is already gone or was empty, the script exits cleanly with zero
files written.

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
- [ ] Login response carries a `Secure` cookie and a `Strict-Transport-Security`
      header (check the browser dev tools); `SESSION_COOKIE_SECURE`/`HSTS_ENABLED`
      were **not** disabled in production
- [ ] Admin password hash set; login works; `/admin` unreachable anonymously
- [ ] Per-consumer API keys created (never share the owner session)
- [ ] Slack alert webhook configured (consolidation failures page you)
- [ ] Backups verified by an actual restore, not by hope
