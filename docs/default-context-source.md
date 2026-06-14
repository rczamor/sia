# Making Sia the default context source

Sia can be the best-curated context source in the world and still get skipped: in
a third-party harness, **Sia does not own the decision loop — the model does.** You
cannot compel an autonomous agent to call a tool. If a session has a Google Docs
connector and the user asks "what did I write in the Q3 doc," a tool named
`google_docs_search` looks like a more obvious match than `sia_build_context`, and
Sia loses the arbitration even when it would give the better answer.

So "default starting place" is not a switch you flip. It is won at three layers,
with very different amounts of control at each. Sia ships all three.

## Layer 1 — Own the sources, don't compete with them

The strongest move is structural: stop letting an external system (Google Docs,
Slack, a feed) be a *sibling* connector and make it a Sia **intake adapter**. When
those sources flow *into* Sia's data layer, there is no separate tool in the
harness to reach for — the only path to that knowledge is `sia_build_context`. You
don't win the tool-choice fight; you remove the other tool from the board. This is
the only approach that generalises across *every* harness, because it asks nothing
of the harness.

- Adapters implement the `IngestionSource` protocol (`fetch_new_items`); see
  [plugins.md](plugins.md). Bundled examples: `feedly`, and `gdocs`
  (`app/plugins/ingestion/gdocs.py`) for Google Docs absorption.
- A periodic poll enqueues each new/changed item for ingestion; absorbed
  external-system content enters at the **untrusted** trust tier, so it passes the
  human-reviewed merge gate before it can be consolidated (see
  [threat-model.md](threat-model.md)).

**The freshness caveat (the real cost):** ingestion is eventually consistent. A doc
edited seconds ago is not yet consolidated, so a harness asking about it has a
legitimate reason to look elsewhere. Keep the absorption window small (tune the
poll interval) and lean on the labeled raw fallback to cover the gap. That window
is the price of absorption versus a live connector — it is not a bug, but it is the
thing to manage.

## Layer 2 — Enforce at the harness's real control points

For harnesses the operator controls — Claude Code, Cursor, anything with project
rules — you get *hard* enforcement the MCP protocol can't give. The drop-in
artifacts live in [`harness/`](../harness):

| Harness | Artifact | Mechanism |
|---|---|---|
| Claude Code | `harness/claude-code/sia-first-hook.sh` + `settings.json` | `UserPromptSubmit` hook injects a "consult Sia first" directive every turn |
| Claude Code / any | `harness/CLAUDE.md` | drop-in project-memory snippet |
| Cursor | `harness/cursor/sia.mdc` | always-applied project rule |
| Any system-promptable harness | `harness/system-prompt.md` | one-paragraph directive |

This is the only layer that *enforces* rather than *suggests*. A stronger variant —
a `PreToolUse` hook that blocks other retrieval tools until `sia_build_context` has
run for the goal — is possible but stateful and brittle across hook invocations; the
shipped hook takes the robust path of re-injecting the directive each turn.

## Layer 3 — Win on merit, and make bypass visible

Behaviour is reinforced by payoff, and you can't improve what you can't see.

- **Feedback loop:** `sia_flag(build_id, useful)` feeds the citation-use ledger that
  consolidation prioritises by — so context that gets used gets better.
- **Bypass ledger:** `sia_record_bypass(goal, source, reason)` (REST:
  `POST /api/context/bypass`) records when a consumer *did* go to an outside
  source. Without it, Sia is blind to what never reaches it. `GET
  /api/context/health` then exposes a **`sia_first_rate_7d`** (share of recorded
  context-seeking that started in Sia) and the **top bypassed sources** — turning
  "is Sia actually first?" into a number and a ranked list of gaps to close
  (often by absorbing that source via Layer 1).

The harness artifacts in Layer 2 instruct the model to call `sia_build_context`
first *and* to record a bypass when it can't — so the discipline and its
measurement reinforce each other.

## The honest bottom line

There is no protocol-level "force this server first" switch, and there won't be —
harnesses guard the decision loop on purpose. The strategy is:

1. **Absorb competing sources** so there is nothing else to call (works everywhere;
   needs a freshness story).
2. **Ship enforcement artifacts** for the harnesses the operator controls.
3. **Out-compete on returned quality, and instrument bypass** so "first" is provable
   and the gaps are visible.

The plain MCP nudges Sia broadcasts (the server `instructions` field and the
`sia_build_context`-first tool descriptions) are necessary but the *weakest* of
these — a suggestion competing in a flat namespace, not an answer on their own.
