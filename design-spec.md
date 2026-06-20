# Sia — Interface Design Spec

A brief for **Claude Design**: produce a few design mockups for Sia's interface that
match Riché Zamor's personal brand and, above all, make the UI tell the truth about
what Sia actually does.

> **How to use this file.** Hand it to Claude Design as the design brief. It contains
> (1) the product truth and the specific misalignment to fix, (2) brand foundations
> as concrete design tokens, (3) the screens to mock up with the intent of each, and
> (4) a component vocabulary. Brand tokens marked **[confirm]** are sensible defaults
> derived from Sia's positioning — replace them with the canonical personal-brand
> values before final mockups if they differ.

---

## 1. The one-line problem

**The current UI looks like a generic content database; the product is a context
engine.** The screens foreground *storage* (counts of sources, thoughts, artifacts;
a search box; tables of rows). They hide the thing that makes Sia Sia: it *generates*
decision-ready context — scored, cited, budget-shaped — through consolidation, and it
*measures* whether that context was good and what it cost. The redesign's job is to
invert that: put the engine in front, push the raw store to the back.

---

## 2. What Sia actually is (product truth)

Sia is an **open-source Context Engine**. It serves decision-ready context to any AI
agent harness (Claude, ChatGPT, Cursor — anything that speaks MCP). Its thesis: *data
is not context*. Context must be actively generated — curated, synthesized,
consolidated, prioritized, stored — at a dedicated layer most AI systems skip.

It is **not a chat app and not a CRM**. The human operator does not "use" Sia to read
content; they *tend the engine* that feeds their agents. The primary question every
screen should help answer is: **"Is the engine producing good context, and can I trust
and improve it?"**

What the engine genuinely does (all of this is live functionality the UI must reflect):

- **Intake** — URLs, webhooks, captures are fetched (SSRF-guarded), classified,
  embedded, and assigned a **trust tier**. Suspicious content is **quarantined** before
  it can ever be consolidated.
- **Three consolidation clocks** turn raw intake into a **git-backed Markdown store** of
  topic files with **cited claims**:
  - **light** — post-ingest matching
  - **REM** — daily re-gisting, contradiction detection, citation-use priorities
  - **deep** — weekly entity linking, pruning, skill synthesis
- **A human review gate** — anything *untrusted-derived* merges into the store only
  through a reviewed **diff** (approve / reject).
- **A knowledge graph** (topics, skills, entities, sources) with overlays for structure,
  **freshness/decay**, and **citation use**.
- **The ContextBuilder** assembles **cited, scored, budget-shaped artifacts** per
  **principal** (owner / per-purpose agents / anonymous visitors), with **skills
  progressively disclosed** and raw retrieval only as a labeled fallback.
- **Everything is measured** — every build gets a `context_score`, every model call is
  in a **lineage ledger**, and health surfaces fallback rate, cost per decision, build
  latency, and how often consumers went around Sia ("bypasses").

Vocabulary to honor (locked terminology — use these exact words in UI copy):
**Context Engine** (category), **Context Architecture** (the thesis/pillar),
**four layers: Data → Retrieval → Context → Inference** (Sia owns the first three;
Inference belongs to the consuming harness). Pillars currently in data:
**Context Architecture**, **Product Management**, **Leadership**.

---

## 3. The misalignment, screen by screen

| Current screen | What it shows today | Why it misrepresents the product | What it should foreground |
|---|---|---|---|
| **Dashboard** | "Total Items / Sources / Thoughts / Artifacts" stat cards + a paste-a-URL box + a table of recent ingestions | Frames Sia as a pile of stored items. These counts are the *least* important numbers. | Engine status: are builds healthy, are the clocks running, is anything waiting for review, what's the context score trend. |
| **Inspector** | A buried tab; a plain form → a table of served sections | This is the **money screen** — proof the engine serves cited, scored, budgeted context — yet it's treated as a debug utility. | Promote to the hero experience. Make a build *feel* like an artifact being assembled and scored. |
| **Health** | A wall of equal-weight stat cards + four stacked tables | The most strategic data (fallback rate, cost/decision, bypasses) reads like a server status page. | A legible "is the engine earning its keep" narrative with trend, not a metrics dump. |
| **Knowledge** | Search box + flat result cards with raw scores | Reinforces "Sia = searchable database." Retrieval is the layer *below* the product. | Frame as inspecting the Data/Retrieval layer that *feeds* consolidation — clearly subordinate to the store. |
| **Review** | Raw monospace git diff with Approve/Reject | Functionally correct but visually alarming/unbranded; the **trust gate** is a signature feature shown as a terminal dump. | A confident, legible "merge gate" — provenance, trust tier, and a readable diff. |
| **Graph** | Cytoscape canvas + filter buttons | Good bones, but generic; overlays (freshness, citation use) are the insight and aren't visually celebrated. | The same graph, but the overlays read as *meaning* (decay, usefulness), branded. |
| **Ingest** | A form | Fine, but disconnected from the trust/quarantine story. | Show intake as the front of a pipeline that ends in consolidation, with trust tier visible. |

Current implementation, for context (the mockups need not preserve it, but should stay
*implementable* — see §9): Jinja2 + HTMX + Pico CSS, dark theme, system-ui font, a
horizontal top nav, and three accent colors used as pillar badges
(`#2563eb` blue, `#7c3aed` violet, `#059669` green).

---

## 4. Design principles

1. **Engine over inventory.** Lead with what the engine produced and how good it was,
   not with how much is stored. Counts are footnotes.
2. **Every claim is cited; show it.** Citation and provenance are the product's
   integrity. Make sources, scores, and lineage first-class, never hidden in a
   `<details>`.
3. **Make the invisible legible.** Consolidation clocks, freshness decay, trust tiers,
   token budgets, and cost are abstract — give each a calm, consistent visual language
   so an operator can read engine state at a glance.
4. **Calm, instrument-grade, editorial.** This is a thinking tool for one expert
   operator, not a consumer dashboard. Restraint, generous whitespace, precise
   typography. No celebratory chrome, no gradients-for-decoration.
5. **Trust is a feature, render it.** Quarantine, the review diff gate, and
   human-in-the-loop merges should look deliberate and reassuring, not like errors.
6. **Honest empty/cold states.** A fresh install has ~0 rows. The first-run experience
   should teach the four-layer model and point to connecting a harness — not show a sad
   pile of zeros.

---

## 5. Brand foundations (design tokens)

> Tokens marked **[confirm]** are derived from Sia's positioning (technical, editorial,
> measured, open-source) and from the accent hues already in the codebase. Swap in the
> canonical personal-brand values where they differ. Everything else is a
> recommendation tuned to those principles.

### 5.1 Color

A restrained, near-monochrome **instrument** palette with a single confident accent and
a small, *semantic* (not decorative) secondary set. Ship **dark as the primary theme**
(the current app is dark; it suits a focus tool), with a light theme defined for parity.

**Neutrals (dark theme, primary) [confirm against brand]**

| Token | Hex | Use |
|---|---|---|
| `--bg` | `#0B0D10` | App background (near-black, slightly cool) |
| `--surface` | `#141821` | Cards, panels |
| `--surface-2` | `#1C212C` | Raised / hovered surfaces |
| `--border` | `#262C38` | Hairlines, dividers |
| `--text` | `#E7EAF0` | Primary text |
| `--text-muted` | `#9AA3B2` | Secondary text, labels |
| `--text-faint` | `#5C6675` | Tertiary, metadata |

**Accent — "signal" [confirm: this is the brand's primary]**

| Token | Hex | Use |
|---|---|---|
| `--accent` | `#3B82F6` | Primary actions, active nav, the "engine is working" hue (carried from existing `#2563eb`, brightened for dark UI) |
| `--accent-weak` | `#1E2A44` | Accent-tinted fills, selected rows |

**Pillar hues (keep — already meaningful in data)**

| Pillar | Hex |
|---|---|
| Context Architecture | `#3B82F6` (blue) |
| Product Management | `#8B5CF6` (violet) |
| Leadership | `#10B981` (green) |

**Semantic / state (used sparingly, only to mean something)**

| Token | Hex | Means |
|---|---|---|
| `--ok` | `#34D399` | Healthy, fresh, trusted, approved |
| `--warn` | `#FBBF24` | Stale, low coverage, needs attention |
| `--danger` | `#F87171` | Failure, contradiction, quarantined, rejected |
| `--diff-add` | `#4ADE80` | Diff additions (review) |
| `--diff-del` | `#F87171` | Diff deletions (review) |
| `--diff-hunk` | `#38BDF8` | Diff hunk headers |

**Freshness/decay ramp** (for graph + health) — a green→amber→grey gradient so "fresh"
reads warm-alive and "decayed" reads cool-faded: `#34D399 → #FBBF24 → #5C6675`.

### 5.2 Typography [confirm against brand]

A two-family system that signals "editorial thinking tool built by an engineer":

- **Display / headings** — a confident humanist serif **or** a precise grotesque.
  Recommended default: **a modern serif** (e.g. *Newsreader*, *Source Serif*, or the
  brand's editorial face) for H1/H2 to carry the "thesis / point of view" voice.
  *If the personal brand is sans-only, use a tight grotesque (e.g. Inter Tight) instead.*
- **Body / UI** — **Inter** (or system-ui fallback) for all interface text, labels,
  tables.
- **Mono** — **JetBrains Mono** / **IBM Plex Mono** for: token counts, scores, IDs,
  build artifacts, diffs, and the Markdown the harness receives. Monospace is a
  *brand signal* here — it says "this is real, inspectable machinery."

Scale (rem): `2.25 / 1.75 / 1.375 / 1.125 / 1.0 / 0.875 / 0.75`. Generous line-height
(1.5 body, 1.25 headings). Numerals **tabular** everywhere metrics appear.

### 5.3 Space, shape, depth

- 8px spacing grid; sections breathe (24–40px gaps).
- **Low radius** — 8px on cards, 6px on controls, full-round only on chips/badges.
  Restraint over playfulness.
- **Depth by hairline + tint, not heavy shadow.** Use `--border` and `--surface-2`
  rather than drop shadows. At most one soft shadow on overlays/modals.
- Max content width ~1200px; the Inspector and Health can go full-width for tables.

### 5.4 Motion

Minimal and functional. Build assembly can show a brief, calm staged reveal (sections
appearing as "served"). Consolidation clock states can pulse softly when running.
No decorative animation. Respect `prefers-reduced-motion`.

### 5.5 Iconography & data-viz

- Thin-line icons (1.5px), geometric, consistent — Lucide-style.
- **Score meters** as the signature data element: a horizontal 0–1 meter with a tabular
  numeric readout; color shifts ok→warn→danger across the range.
- **Sparklines** for 7-day trends (context score, cost/decision) — minimal, axis-less.
- Charts inherit neutrals + the single accent; never a rainbow.

---

## 6. Information architecture

Re-order navigation so it reads as **Engine → Knowledge → Operations**, not a flat list:

```
Sia ▸ Context Engine
  Overview        (was "Dashboard" — engine status, not inventory)
  Inspector       (promoted — run/inspect a context build)
  Health          (is the engine earning its keep)
  ── Knowledge ──
  Store / Graph   (the consolidated context store + graph view)
  Search          (was "Knowledge" — Data/Retrieval layer, subordinate)
  ── Operations ──
  Intake          (was "Ingest")
  Review          (the trust gate; show a badge with pending count)
```

A persistent **engine status strip** (small, top-right or in a header rail): clocks
running ●, builds today, pending reviews, current avg context score. The operator
should know the engine's pulse from any screen.

---

## 7. Screens to mock up

Produce mockups for these, in priority order. **Dark theme primary**; show **Overview**
and **Inspector** in both dark and light. Desktop first (1440px); show responsive
behavior for Overview.

### 7.1 Overview (hero of the redesign) — *replaces Dashboard*
The answer to "how is my engine doing?" in one glance.
- **Top:** a context-quality summary — avg `context_score` (7d) with a sparkline,
  fallback rate, cost per decision, builds today. Use score meters, not bare cards.
- **Clocks:** the three consolidation clocks (light / REM / deep) as live status —
  last run, next run, runs vs. failures, a soft pulse when running.
- **Attention queue:** what needs the operator — pending reviews (count + jump),
  quarantined intake, stale topics, contradictions detected.
- **Recent builds:** a compact list (goal, principal, score, coverage, fallback?,
  tokens) — each row links into the Inspector for that build.
- Inventory counts (sources/thoughts/artifacts) appear **once, small, as a footnote**,
  not as the headline.
- **Cold-start variant:** ~0 rows — teach the four-layer model, show "connect a harness"
  and "ingest your first source" as the two next steps.

### 7.2 Inspector — *the proof screen*
Run a context build as any principal and see exactly what was served, and why.
- **Input:** Goal (the decision needing context), "Run as" principal (with its token
  budget shown), optional budget override. Make this feel like posing a question to the
  engine, not filling a form.
- **Result = an artifact, rendered as an artifact:**
  - Header band: build id (mono), principal, **tokens used / budget** as a budget bar,
    **coverage** meter, section count, skill count, **fallback yes/no** as a clear flag.
  - **Cautions** surfaced prominently if present (not buried).
  - **Served sections** table: path · kind · *reason* (ranked / graph-expansion /
    fallback — color-coded) · tokens. The "reason" is the engine showing its work.
  - **Skills (progressive disclosure):** title · trigger · "full body vs stub" · est.
    tokens — visualize that skills are disclosed, not dumped.
  - **Unconsolidated fallback** (if any): clearly labeled as the lower-trust path.
  - **The Markdown the harness receives:** first-class, in a mono panel with a copy
    button — *this is what the agent sees*. Not hidden behind a disclosure.
- Optional flourish: a brief staged reveal as sections are "served" into the budget bar.

### 7.3 Health — *is the engine earning its keep*
Turn the metric dump into a narrative.
- A headline read: context score trend, fallback rate, **cost per decision**, avg build
  latency — each with a 7d sparkline and a plain-language "good/watch/bad" cue.
- **Consolidation clocks** table → status cards with run/failure counts.
- **Store composition & freshness** → a small stacked/segmented view by kind + status,
  with average age and the freshness ramp.
- **Bypasses (30d):** "where consumers went outside Sia" framed as *coverage gaps to
  close*, with the source and count — an opportunity list, not an error log.

### 7.4 Store / Graph
The consolidated Markdown store and the knowledge graph in one place.
- Keep the Cytoscape graph; brand it. Node types: topic / skill / entity (legend).
- **Overlays as the headline feature:** pillar (structure), freshness (decay — use the
  ramp), citation use 30d (usefulness). Make switching overlays feel like switching lenses.
- A side panel: selecting a node shows the topic file, its cited claims, freshness,
  and citation count.

### 7.5 Review — *the trust gate*
Untrusted-derived changes reach the store only here.
- Per pending item: the branch/proposal, **provenance + trust tier** of what produced it,
  and a **readable** diff (keep add/del/hunk colors, but legible line height and a real
  panel — not an alarming terminal block).
- Approve / Reject as deliberate, weighted actions with confirmation. Empty state:
  "Nothing waiting — the store is current," reassuring, not blank.

### 7.6 Search — *subordinate to the store*
- The existing search, restyled, but framed as inspecting the **Data / Retrieval** layer
  beneath consolidation. Result cards: title, preview, entity type, pillar badge, and a
  retrieval score meter. A persistent note that consolidated context (not raw retrieval)
  is what agents receive.

### 7.7 Intake — *front of the pipeline*
- URL / webhook / quick-thought intake, but shown as **step 1 of a pipeline** that flows
  to classify → embed → trust-tier → consolidate. Show the trust tier a new item will
  get and that suspicious content is quarantined.

---

## 8. Component vocabulary

Define these once; reuse across screens:

- **Score meter** — 0–1 horizontal meter + tabular numeric; ok→warn→danger color.
- **Budget bar** — tokens used / budget, with overflow styling.
- **Trust-tier chip** — small chip: trusted / untrusted-derived / quarantined
  (`--ok` / `--warn` / `--danger`).
- **Pillar badge** — rounded chip in the three pillar hues (existing pattern, refined).
- **Clock status** — label + last/next run + running pulse + failure indicator.
- **Citation reference** — an inline, clickable source token (mono), the integrity unit.
- **Diff panel** — readable, branded, add/del/hunk colors on a calm surface.
- **Reason tag** — ranked / graph-expansion / fallback, color-coded, for served sections.
- **Freshness dot** — node/row freshness via the green→amber→grey ramp.
- **Engine status strip** — global pulse: clocks, builds today, pending reviews, score.
- **Empty/cold state block** — illustrative, instructional, points to the next action.

---

## 9. Constraints & deliverables

**Implementation reality (don't design something un-buildable).** The app renders with
Jinja2 + HTMX + server-side partials, currently on Pico CSS. The mockups may propose a
custom design system (preferred) but should stay achievable with **server-rendered HTML
+ CSS custom properties + light HTMX interactions** — no heavy SPA framework, no
client-side state machine. Graph view uses Cytoscape and stays. Favor CSS the team can
implement as design tokens (the `--bg`/`--surface`/… set above maps directly to CSS
variables and a Pico re-theme).

**Accessibility:** WCAG AA contrast in both themes; tabular numerals for all metrics;
`prefers-reduced-motion` honored; full keyboard path through Inspector and Review.

**Deliver:**
1. **Overview** (dark + light, plus cold-start variant) — the hero.
2. **Inspector** (dark + light) with a populated artifact result.
3. **Health**, **Store/Graph**, **Review** (dark).
4. **Search** and **Intake** (dark) — can be lighter-fidelity.
5. A **one-page style tile**: the token set above realized — color chips, type scale,
   the score meter / budget bar / trust chip / pillar badge / clock status / diff panel.
6. Annotations calling out where each screen *inverts* the old "inventory" framing toward
   the "engine" framing (§3).

Formats: high-fidelity static frames (PNG/figma-style) at 1440px desktop, plus the
style tile. A few key responsive frames for Overview.

---

## 10. Brand inputs to confirm

Before final mockups, confirm or replace these against Riché's canonical personal brand
(the personal site couldn't be auto-read for this draft):

- [ ] **Primary brand color** — is `#3B82F6` (signal blue) right, or is there a canonical
      brand accent? Provide hex.
- [ ] **Heading typeface** — editorial **serif** (recommended, matches a "thesis" voice)
      vs. a grotesque sans. Provide the licensed family.
- [ ] **Body/UI + mono typefaces** — confirm Inter + JetBrains Mono, or substitute.
- [ ] **Default theme** — confirm **dark-primary** (recommended) vs. light-primary.
- [ ] **Logo / wordmark** — supply the Sia mark and any personal monogram, plus clear-space
      and minimum-size rules.
- [ ] **Voice** — confirm the locked vocabulary (§2) and tone: precise, declarative,
      lightly opinionated ("data is not context"), never salesy.
