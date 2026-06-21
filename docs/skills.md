# Skills

Sia stores procedural knowledge as `skills/<slug>/SKILL.md` files inside the
git-backed context store. The format follows the Memento-Skills pattern: a cheap
trigger stub first, then a compact procedure only when the ContextBuilder has
budget and the goal calls for it.

## Contract

Each skill includes front matter with:

- `memento_contract_version: "1.0"`
- `progressive_disclosure: true`
- `trigger_description`: when an agent should read the full file
- `token_cost_estimate`: approximate full-body cost
- `maturity`: `draft`, `tested`, or `proven`
- `derived_from`: evidence refs such as `artifact:<uuid>` or topic paths

The body uses `## Procedure`, optional `## Examples`, and `## Failure modes`.

## Lifecycle

The deep clock drafts skills from expertise artifacts and lineage patterns. Drafts
always land on `consolidation/<date>-skills` review branches because approved
skills can steer downstream agent behavior. The review gate is the human approval
point before a skill reaches `main`.

## ContextBuilder behavior

ContextBuilder serves matching skill stubs by default: title, path, trigger, and
token estimate. It includes the full skill body only when the context budget can
comfortably hold it. This keeps routine builds cheap while still giving agents
procedural knowledge when it matters.
