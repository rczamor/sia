# Sia threat model

Sia ingests untrusted web content and serves consolidated context to AI agents.
The two assets that matter: the **context store** (what agents will believe) and
the **operator's credentials/data**.

## 1. Memory poisoning (the defining threat for a context engine)

An attacker who can get content ingested (a planted article, a hijacked feed, a
poisoned Slack link) tries to inject claims or instructions that agents will later
treat as consolidated truth.

Defenses, in order:
1. **Quarantine at intake** (`app/data/quarantine.py`): injection markers,
   oversized payloads, off-domain content are stored for audit but excluded from
   every consolidation query until an operator clears the flag.
2. **Trust tiers**: bare URLs and feed items are `untrusted`; only owner-authored
   thoughts/expertise are `owner`-tier.
3. **The review gate**: anything untrusted-derived can only enter the store
   through a `consolidation/<date>` branch and a human reading the actual diff.
   Markdown-canonical storage exists precisely so these diffs are reviewable.
4. **Citations**: every claim carries `[source:<uuid>]`; `sia_resolve_source`
   resolves provenance, including its trust tier.

**Forensics — "which memory caused this output?"**: a served artifact carries its
`build_id`; `context_builds.served` lists exactly which files (and which commit,
via `context_sections.commit_sha`) were served; `git log -S "<claim text>"` in the
store pinpoints the commit and consolidation run that introduced a claim;
`consolidation_runs.input_ids` links back to the raw source rows.

## 2. SSRF via ingestion

Operator-supplied URLs are fetched. `app/data/url_safety.py` allowlists http/https,
refuses non-public addresses (loopback, RFC1918, link-local incl. 169.254.169.254),
re-validates every redirect hop, and caps response size. **Residual**: DNS
rebinding between resolve and connect is not pinned; mitigate at the network layer
(egress filtering) if your deployment is sensitive.

## 3. Credential theft / privilege escalation

- Secrets are environment-only; the database stores no credentials (the legacy
  plaintext `plugins.credentials` column was dropped in migration 003).
- API keys: random 256-bit, sha256-at-rest, shown once, rotatable, revocable.
- Deny-by-default middleware; owner-only surface for admin/config/review/principals;
  visitor principal is public-only with no raw-data fallback.
- Session cookie: HttpOnly, SameSite=Lax; Secure (and HSTS) when the request is
  https or `FORCE_HTTPS=true` — set the latter behind a TLS-terminating proxy,
  since uvicorn only sees https itself when `--proxy-headers` is trusted via
  `FORWARDED_ALLOW_IPS`. Cross-origin unsafe methods with a session cookie are
  refused (CSRF defense-in-depth).
- Rate limits on login and anonymous builds (in-memory, per-process — use a
  shared store before scaling out).

## 4. Data exfiltration through served context

A compromised or over-curious consumer sees only what its principal allows:
visibility filtering happens at store reads (builder, MCP list/read tools), not
just at routes. Private topics never reach public principals, including via graph
expansion. Every build is audited per principal.

The **consolidated store** has a per-row `visibility` column and is filtered
everywhere. The **raw data layer** (`source_content`, `my_thoughts`,
`expertise_artifacts`) has no such column — it is the owner's private corpus — so
access to it requires a principal trusted with private visibility
(`Principal.can_read_raw_data`): owner, or an agent the owner explicitly granted
private access. This gate covers `/api/knowledge/*` and `/api/ingest/*` (owner-only
via middleware), and the MCP tools `sia_search`, `sia_resolve_source`,
`sia_add_thought`, `sia_add_source`. A public-only agent or visitor cannot read,
search, resolve, or write the raw layer; they consume only the visibility-filtered
consolidated store via `sia_build_context`. Entity nodes/edges carry no private
content and are exposed only through the owner-only graph endpoint.

## 5. Supply chain

- Dependencies are pinned by `constraints.txt` (regenerate with `make lock`); the
  Docker image and CI install against it, so builds are reproducible. GitHub
  Actions are pinned to commit SHAs. Dependabot refreshes both weekly; pip-audit +
  gitleaks run in CI; the container runs as a non-root user.
- The admin UI executes **no third-party-hosted code**: the three frontend assets
  (pico.css, htmx, cytoscape) are vendored at pinned versions under
  `app/static/vendor/`, and the default `Content-Security-Policy` is
  `default-src 'self'` — inline-script injection, `eval`, off-origin scripts,
  framing, and base-uri tricks are all blocked. `CSP_HEADER` overrides the policy
  if you need to loosen or tighten it.

## Out of scope (deliberately)

- Multi-tenant isolation: Sia is single-operator by design.
- DoS beyond basic rate limiting: front with a proxy/CDN.
