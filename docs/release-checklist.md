# Release checklist

Run before tagging a release. CI enforces most of this on every PR; the manual
steps prove the install story end to end.

## Automated (must be green on the release commit)

- [ ] `ruff check app/ tests/ scripts/` — lint
- [ ] `lint-imports` — four-layer architecture contracts
- [ ] `pytest` — full suite, incl. security-header/CSP tests, SSRF/ingestion
      tests, cookie/HSTS tests, vendored-asset hash check
- [ ] `pip-audit` against the locked environment (CI security job)
- [ ] Secret scan (gitleaks) clean
- [ ] `bandit -c pyproject.toml -r app/ scripts/` clean (suppressions are inline
      and justified)
- [ ] `python scripts/verify_vendor_assets.py` — assets match pinned hashes
- [ ] CDN-reference check clean (no third-party script/style origins)
- [ ] `lockfile-fresh` job — `constraints.txt` still satisfies `pyproject.toml`
- [ ] `wheel-smoke` job — wheel installs and imports from outside the repo with
      templates/static included

## Manual smoke tests

- [ ] **Fresh compose install**: clean checkout, `cp .env.example .env`, fill
      secrets, `docker compose --profile bundled-db up` — engine preflights,
      migrates a blank DB, serves; admin login works.
- [ ] **Fresh wheel install**: `pip wheel --no-deps -w dist . && pip install
      dist/*.whl` in a clean venv, then `python -c "import app.main"` from a
      different directory.
- [ ] **Managed Postgres path**: point `DATABASE_URL` at a scratch Neon/RDS DB,
      `python scripts/preflight_db.py` reports OK (or the exact privilege fix),
      `alembic upgrade head` succeeds.
- [ ] **Admin behind a reverse proxy**: login through the TLS proxy; the session
      cookie shows `Secure; HttpOnly; SameSite=Lax` and the response carries
      `Strict-Transport-Security` (browser dev tools).
- [ ] **MCP auth smoke test**: a per-purpose API key reaches `sia_build_context`
      via `/mcp`; a revoked key gets 401; a public-only key gets no private
      content.
- [ ] **Ingestion SSRF**: `POST /api/ingest/url` with `http://169.254.169.254/`
      and `http://localhost/` are refused.

## Paperwork

- [ ] Version bumped in `pyproject.toml`
- [ ] `docs/supply-chain.md` matches reality (vendored versions, lock policy)
- [ ] SECURITY.md contact/disclosure policy still correct
