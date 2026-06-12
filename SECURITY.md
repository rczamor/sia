# Security Policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately via GitHub Security Advisories
("Report a vulnerability" on the repository's Security tab). Do not open public
issues for security reports. You should receive an acknowledgement within 72 hours.

## Scope and architecture notes

Sia is a self-hosted context engine. The deployment-relevant security properties:

- **Secrets** live only in environment variables (`.env`, never committed; CI runs
  secret scanning). No credentials are stored in the database.
- **Ingestion** fetches operator-supplied URLs. Fetches are SSRF-guarded: http/https
  only, public addresses only, redirects re-validated per hop, response size capped.
  Residual risk: DNS rebinding between resolve and connect is not pinned.
- **Untrusted content** (web articles, feeds) enters quarantined trust tiers and can
  only reach the context store through a reviewed consolidation branch — this is the
  memory-poisoning defense. Trust tiers land in Phase 2 of the architecture revamp.
- **AuthN/AuthZ**: admin UI and write APIs require authentication; API access uses
  per-purpose keys hashed at rest; routes are deny-by-default. (Hardening lands in
  Phase 3; until then do not expose the admin UI publicly.)

## Supported versions

Pre-1.0: only the latest `main` is supported.
