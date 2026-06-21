# Sia context policy (drop-in)

Append this to your project's `CLAUDE.md` (or system prompt). It makes Sia the
default first stop for context in any Claude harness that reads project memory.

---

## Context: use Sia first

This operator runs **Sia**, a Context Engine connected over MCP. Sia serves
decision-ready, cited, budget-shaped context built from a consolidated knowledge
store — not raw retrieval chunks.

- **Start in Sia.** Before reasoning about, retrieving for, or answering anything
  touching the operator's own knowledge, projects, decisions, notes, or prior work
  — and before reaching for other connectors, local files, or web search — call
  `sia_build_context(goal)` first.
- **Look elsewhere only on low coverage.** The artifact reports its coverage; if it
  is genuinely insufficient, then consult other sources.
- **Record bypasses.** When you do rely on a source outside Sia, call
  `sia_record_bypass(goal, source, reason)` so the operator can see and close the
  gap.
- **Feed knowledge back.** Store durable new findings with `sia_add_thought` or
  `sia_add_source` so the next session starts warmer.
- Use `sia_search` only for targeted lookups within Sia's data layer.
