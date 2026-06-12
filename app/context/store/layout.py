"""Store scaffold: layout, spec, and seed templates committed on first boot."""

from datetime import datetime, timezone

from app.context.store.gitstore import GitContextStore

STORE_SPEC = """# Sia Context Store — Specification

This repository is Sia's Context-layer storage: consolidated meaning as Markdown
files with YAML front matter. Files are canonical; Postgres holds a rebuildable
index. Git history is the audit trail.

## Layout
- `INDEX.md` — generated priority map (never edit by hand)
- `profile/` — identity.md, goals.md, principals.md (owner-edited)
- `knowledge/<pillar>/*.md` — topic files: declarative knowledge
- `skills/<slug>/SKILL.md` — skill files: procedural knowledge
- `theses/*.md` — long-form positions
- `tensions/` — contradictions.md, open-questions.md
- `.sia/` — spec, regression fixtures, lock

## Topic front matter
id, pillar, type, status (active|stale|archived), confidence (0-1), priority (0-1),
visibility (public|private), freshness (ISO date), last_consolidated, sources[],
supersedes, related[]

Body sections: `## Gist` (<=150 words), `## Key claims` (each cited with
[source:<uuid>] or [thought:<uuid>]), `## Tensions`, `## Implications`.

## Skill front matter
Adds: trigger_description, token_cost_estimate, maturity (draft|tested|proven),
derived_from[].
Body: procedure steps, examples, failure modes.

## Trust gate
Owner-tier writes commit to `main`. Anything derived from untrusted intake lands on
a `consolidation/<date>` branch and merges only through human review of the diff.
Pruning is a status change + archive commit, never deletion.

## Linking
`related:` front matter and `[[wikilinks]]` in bodies feed the knowledge graph
(Obsidian-compatible syntax).
"""

IDENTITY_TEMPLATE = """---
id: profile-identity
visibility: private
priority: 1.0
---

# Identity

<!-- Owner-authored. Example voice/identity notes (seeded from the legacy
voice_master prompt — edit to fit): -->

A product leader and AI architect who builds context-aware systems.

- Authoritative but accessible — has built these systems, not just studied them
- Practitioner-first — grounds claims in real architecture decisions
- Contrarian with substance — challenges conventional wisdom, with evidence
- Warm and direct — no jargon for jargon's sake, no hedging

Core thesis: "Data is not context. Context must be actively synthesized — not
retrieved — before it has value in any AI system."
"""

GOALS_TEMPLATE = """---
id: profile-goals
visibility: private
priority: 1.0
---

# Goals

<!-- Owner-authored: current goals, ranked. The ContextBuilder reserves budget for
extracts from this file on every build. -->

1. (add your goals here)
"""

PRINCIPALS_TEMPLATE = """---
id: profile-principals
visibility: private
priority: 1.0
---

# Principals

<!-- Who may consume context, and with what visibility and budget. Managed by the
principal registry; this file documents intent. -->

- owner: full visibility, 12k token budget, raw-data fallback allowed
- agent-*: per-purpose keys, 8k budget, per-grant visibility
- visitor: public-only, 2.5k budget, no raw fallback
"""

TENSIONS_TEMPLATE = """---
id: tensions-contradictions
visibility: private
priority: 0.8
---

# Contradictions

<!-- Maintained by the REM clock: claims that conflict, with citations. -->
"""

OPEN_QUESTIONS_TEMPLATE = """---
id: tensions-open-questions
visibility: private
priority: 0.8
---

# Open questions
"""


async def scaffold_store(store: GitContextStore) -> str:
    """Create the initial layout if the store is empty. Returns HEAD sha."""
    existing = await store.list_paths()
    if existing:
        return await store.head_sha()

    today = datetime.now(timezone.utc).date().isoformat()
    files = {
        ".sia/store-spec.md": STORE_SPEC,
        "INDEX.md": f"# INDEX\n\nGenerated {today}. Empty store — ingest and consolidate.\n",
        "profile/identity.md": IDENTITY_TEMPLATE,
        "profile/goals.md": GOALS_TEMPLATE,
        "profile/principals.md": PRINCIPALS_TEMPLATE,
        "tensions/contradictions.md": TENSIONS_TEMPLATE,
        "tensions/open-questions.md": OPEN_QUESTIONS_TEMPLATE,
        "knowledge/.gitkeep": "",
        "skills/.gitkeep": "",
        "theses/.gitkeep": "",
        ".sia/regression/.gitkeep": "",
    }
    return await store.commit(files, "chore: scaffold context store")
