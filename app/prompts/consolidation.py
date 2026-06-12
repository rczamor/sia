"""Prompts for the consolidation clocks (Context-layer internal LLM operations)."""

LIGHT_MATCH = """You are Sia's light consolidation clock. A new item arrived in the data layer.
Decide whether it belongs to an existing topic file or warrants a new one, and extract
the decision-relevant claims.

Existing candidate topics (path :: gist):
{candidates}

New item (id {source_id}, type {source_type}):
Title: {title}
Summary: {summary}
Content excerpt:
{excerpt}

Rules:
- Claims must be specific, decision-relevant, and verifiable against the item.
- 1-4 claims maximum. No marketing language.
- If the item matches an existing topic, return its exact path.
- A new topic needs a short kebab-case slug and a one-sentence gist.

Return JSON:
{{
  "action": "append" | "new_topic" | "skip",
  "topic_path": "knowledge/<pillar>/<slug>.md (for append)",
  "new_topic": {{"slug": "...", "title": "...", "pillar": "{pillar}", "gist": "..."}},
  "claims": ["..."]
}}"""

REM_GIST = """You are Sia's REM consolidation clock. Rewrite this topic file's gist so it
captures the consolidated meaning of its claims in 150 words or fewer. Plain,
specific, decision-ready language. Return JSON: {{"gist": "..."}}

Topic: {title}

Current claims:
{claims}"""

REM_CONTRADICTIONS = """You are Sia's REM consolidation clock. Compare these two topics' claims and
identify genuine contradictions (claims that cannot both be true), not mere tension
of emphasis. Be conservative: most pairs have none.

Topic A ({path_a}):
{claims_a}

Topic B ({path_b}):
{claims_b}

Return JSON: {{"contradictions": [{{"claim_a": "...", "claim_b": "...", "note": "..."}}]}}"""

DEEP_ENTITIES = """You are Sia's deep consolidation clock performing entity linking. From these
topic gists, extract the distinct named entities (people, organizations, tools,
concepts, methods) that connect topics to each other. Only entities appearing in or
clearly implied by at least one gist; prefer canonical names.

Topics (path :: gist):
{topics}

Return JSON:
{{"entities": [{{"name": "...", "type": "person|org|tool|concept|method",
                "mentioned_in": ["<topic path>", "..."]}}]}}"""

DEEP_SKILL = """You are Sia's deep consolidation clock synthesizing a SKILL — consolidated
procedural knowledge (how to do something), the counterpart to topics' declarative
knowledge.

Evidence of repeated practice:
Expertise artifacts:
{artifacts}

Recent operation statistics (lineage):
{lineage_stats}

Draft ONE skill that this system's owner demonstrably uses. It must be a concrete,
repeatable procedure — not a platitude. Return JSON:
{{
  "slug": "kebab-case-name",
  "title": "...",
  "trigger_description": "when an agent should reach for this skill",
  "steps": ["...", "..."],
  "failure_modes": ["..."],
  "derived_from": ["artifact:<uuid>", "..."]
}}
If the evidence is too thin for a genuine skill, return {{"slug": null}}."""
