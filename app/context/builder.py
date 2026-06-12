"""ContextBuilder: deterministic, goal-aware context assembly.

build(goal, principal, budget) -> ContextArtifact

Read-first hierarchy: consolidated Context-layer storage (topics, theses, profile)
is served first; raw Data-layer retrieval happens only as a labeled fallback when
the consolidated store can't cover the goal — and only for principals allowed it.

Steps map to the thesis: curation (similarity x priority x freshness ranking under
the principal's visibility), prioritization (greedy budget selection with reserved
room for goals and cautions), graph expansion (1-hop pull of tensions, related
topics, and required skills the similarity pass missed), progressive disclosure for
skills (stub by default, full body only if budget allows). Not an agent — no LLM in
the build path.
"""

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.graph import GraphService
from app.context.index import freshness_decay
from app.context.principals import Principal
from app.context.store.documents import estimate_tokens
from app.context.store.gitstore import GitContextStore
from app.models.tables import ContextBuilds, ContextSections
from app.providers.base import EmbeddingProvider
from app.retrieval.search import SearchService

SIMILARITY_WEIGHT = 0.55
PRIORITY_WEIGHT = 0.25
FRESHNESS_WEIGHT = 0.20
COVERAGE_THRESHOLD = 0.35
GOALS_RESERVE_FRACTION = 0.10
EXPANSION_RESERVE_FRACTION = 0.12
SKILL_STUB_COUNT = 3
FALLBACK_RESULTS = 5


@dataclass
class ServedSection:
    path: str
    kind: str
    title: str
    score: float
    similarity: float
    tokens: int
    content: str
    reason: str  # ranked | graph_expansion | goals_reserve | caution


@dataclass
class SkillStub:
    path: str
    title: str
    trigger_description: str
    token_cost_estimate: int
    full_body: str | None = None


@dataclass
class ContextArtifact:
    build_id: uuid.UUID
    goal: str
    principal_id: str
    budget_tokens: int
    sections: list[ServedSection] = field(default_factory=list)
    skills: list[SkillStub] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    fallback: list[dict] = field(default_factory=list)
    coverage: float = 0.0
    tokens_used: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "build_id": str(self.build_id),
            "goal": self.goal,
            "principal": self.principal_id,
            "budget_tokens": self.budget_tokens,
            "tokens_used": self.tokens_used,
            "coverage": round(self.coverage, 3),
            "sections": [
                {
                    "path": s.path,
                    "kind": s.kind,
                    "title": s.title,
                    "reason": s.reason,
                    "tokens": s.tokens,
                    "content": s.content,
                }
                for s in self.sections
            ],
            "skills": [
                {
                    "path": s.path,
                    "title": s.title,
                    "trigger": s.trigger_description,
                    "token_cost": s.token_cost_estimate,
                    "body": s.full_body,
                }
                for s in self.skills
            ],
            "cautions": self.cautions,
            "fallback_unconsolidated": self.fallback,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Context for: {self.goal}",
            "",
            f"_Built {self.created_at.isoformat()} for {self.principal_id}; "
            f"{self.tokens_used}/{self.budget_tokens} tokens; coverage {self.coverage:.2f}._",
            "",
        ]
        if self.cautions:
            lines += ["## Cautions", ""]
            lines += [f"- {c}" for c in self.cautions]
            lines.append("")
        for section in self.sections:
            lines += [f"## [{section.kind}] {section.title} ({section.path})", "",
                      section.content.strip(), ""]
        if self.skills:
            lines += ["## Available skills", ""]
            for skill in self.skills:
                lines.append(f"- **{skill.title}** ({skill.path}) — {skill.trigger_description}")
                if skill.full_body:
                    lines += ["", skill.full_body.strip(), ""]
            lines.append("")
        if self.fallback:
            lines += [
                "## UNCONSOLIDATED SOURCES (raw retrieval fallback — treat with caution)",
                "",
            ]
            for item in self.fallback:
                lines.append(f"- [{item['entity_type']}:{item['id']}] {item.get('title') or ''} — "
                             f"{(item.get('content_preview') or '')[:200]}")
        return "\n".join(lines)


class ContextBuilder:
    def __init__(
        self,
        db: AsyncSession,
        store: GitContextStore,
        embedder: EmbeddingProvider,
        search_service: SearchService | None = None,
    ):
        self.db = db
        self.store = store
        self.embedder = embedder
        self.search_service = search_service

    async def build(
        self,
        goal: str,
        principal: Principal,
        budget_tokens: int | None = None,
        pillar_hint: str | None = None,
    ) -> ContextArtifact:
        started = time.monotonic()
        budget = min(budget_tokens or principal.token_budget, principal.token_budget)
        artifact = ContextArtifact(
            build_id=uuid.uuid4(), goal=goal, principal_id=principal.id, budget_tokens=budget
        )

        goal_vector = await self.embedder.embed(goal)
        ranked = await self._rank_sections(goal_vector, principal, pillar_hint)

        # Reserve: goals extract (owner/private principals only) + graph expansion room
        goals_reserve = int(budget * GOALS_RESERVE_FRACTION)
        expansion_reserve = int(budget * EXPANSION_RESERVE_FRACTION)
        spend_ceiling = budget - expansion_reserve

        used = 0
        if "private" in principal.allowed_visibilities:
            used += await self._serve_goals(artifact, goals_reserve)

        # Greedy selection of topics/theses/tensions by composite score
        topic_similarities: list[float] = []
        for row, similarity, score in ranked:
            if row.kind == "skill":
                continue
            tokens = row.token_estimate
            if used + tokens > spend_ceiling:
                continue
            content = await self.store.read(row.path)
            if not content:
                continue
            artifact.sections.append(
                ServedSection(
                    path=row.path, kind=row.kind, title=row.title or row.path,
                    score=score, similarity=similarity, tokens=tokens,
                    content=content, reason="ranked",
                )
            )
            used += tokens
            if row.kind == "topic":
                topic_similarities.append(similarity)

        artifact.coverage = max(topic_similarities, default=0.0)

        # Graph expansion: 1-hop neighbors of what was selected — contradictions
        # become cautions; related topics/skills fill the reserve
        used += await self._expand_graph(artifact, principal, used, budget)

        # Skills: progressive disclosure
        used += await self._serve_skills(artifact, ranked, used, budget)

        # Fallback to raw Data only when the consolidated store can't cover the goal
        if artifact.coverage < COVERAGE_THRESHOLD and principal.allow_fallback:
            await self._fallback(artifact, goal, pillar_hint)

        artifact.tokens_used = used
        duration_ms = int((time.monotonic() - started) * 1000)
        await self._audit(artifact, pillar_hint, duration_ms)
        return artifact

    # --- internals ---

    async def _rank_sections(self, goal_vector, principal: Principal, pillar_hint):
        visibilities = list(principal.allowed_visibilities)
        pillar_clause = "AND (pillar = :pillar OR pillar IS NULL)" if pillar_hint else ""
        sql = text(
            f"""
            SELECT path, 1 - (embedding <=> CAST(:vec AS vector)) AS similarity
            FROM context_sections
            WHERE status = 'active' AND embedding IS NOT NULL
              AND visibility = ANY(:visibilities)
              AND kind IN ('topic', 'thesis', 'tension', 'skill')
              {pillar_clause}
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT 50
            """
        )
        params: dict[str, Any] = {
            "vec": str([float(v) for v in goal_vector]),
            "visibilities": visibilities,
        }
        if pillar_hint:
            params["pillar"] = pillar_hint
        rows = (await self.db.execute(sql, params)).all()
        now = datetime.now(timezone.utc)
        ranked = []
        for path, similarity in rows:
            row = await self.db.get(ContextSections, path)
            if row is None:
                continue
            score = (
                SIMILARITY_WEIGHT * float(similarity)
                + PRIORITY_WEIGHT * row.priority
                + FRESHNESS_WEIGHT * freshness_decay(row.freshness, now)
            )
            ranked.append((row, float(similarity), score))
        ranked.sort(key=lambda r: r[2], reverse=True)
        return ranked

    async def _serve_goals(self, artifact: ContextArtifact, reserve: int) -> int:
        content = await self.store.read("profile/goals.md")
        if not content:
            return 0
        tokens = min(estimate_tokens(content), reserve)
        artifact.sections.insert(
            0,
            ServedSection(
                path="profile/goals.md", kind="profile", title="Goals",
                score=1.0, similarity=1.0, tokens=tokens,
                content=content[: reserve * 4], reason="goals_reserve",
            ),
        )
        return tokens

    async def _expand_graph(
        self, artifact: ContextArtifact, principal: Principal, used: int, budget: int
    ) -> int:
        selected_refs = [
            f"{'skill' if s.kind == 'skill' else 'topic'}:{s.path}"
            for s in artifact.sections
            if s.kind in ("topic", "skill")
        ]
        if not selected_refs:
            return 0
        graph = GraphService(self.db)
        edges = await graph.neighbors(selected_refs, depth=1)
        selected_paths = {s.path for s in artifact.sections}
        added = 0

        for edge in edges:
            if edge["predicate"] == "contradicts":
                artifact.cautions.append(
                    f"Contradiction on record: {edge['subject_ref']} vs {edge['object_ref']} "
                    f"(see tensions/contradictions.md)"
                )
                continue
            if edge["predicate"] not in ("related_to", "requires_skill"):
                continue
            for ref in (edge["subject_ref"], edge["object_ref"]):
                namespace, _, path = ref.partition(":")
                if namespace not in ("topic", "skill") or path in selected_paths:
                    continue
                row = await self.db.get(ContextSections, path)
                if (
                    row is None
                    or row.status != "active"
                    or row.visibility not in principal.allowed_visibilities
                ):
                    continue
                if used + added + row.token_estimate > budget:
                    continue
                content = await self.store.read(path)
                if not content:
                    continue
                artifact.sections.append(
                    ServedSection(
                        path=path, kind=row.kind, title=row.title or path,
                        score=0.0, similarity=0.0, tokens=row.token_estimate,
                        content=content, reason="graph_expansion",
                    )
                )
                selected_paths.add(path)
                added += row.token_estimate
        return added

    async def _serve_skills(
        self, artifact: ContextArtifact, ranked, used: int, budget: int
    ) -> int:
        added = 0
        skill_rows = [(row, sim) for row, sim, _ in ranked if row.kind == "skill"]
        for row, _sim in skill_rows[:SKILL_STUB_COUNT]:
            content = await self.store.read(row.path)
            if not content:
                continue
            from app.context.store.documents import MarkdownSerializer

            document = MarkdownSerializer().loads(row.path, content)
            stub = SkillStub(
                path=row.path,
                title=row.title or row.path,
                trigger_description=str(document.front.get("trigger_description", "")),
                token_cost_estimate=int(
                    document.front.get("token_cost_estimate", row.token_estimate)
                ),
            )
            # progressive disclosure: full body only if it comfortably fits
            if used + added + stub.token_cost_estimate <= budget * 0.9:
                stub.full_body = document.body
                added += stub.token_cost_estimate
            else:
                added += estimate_tokens(stub.title + stub.trigger_description)
            artifact.skills.append(stub)
        return added

    async def _fallback(self, artifact: ContextArtifact, goal: str, pillar_hint) -> None:
        if self.search_service is None:
            return
        results = await self.search_service.search(
            query=goal,
            pillar=[pillar_hint] if pillar_hint else None,
            limit=FALLBACK_RESULTS,
        )
        artifact.fallback = [
            {
                "id": str(r["id"]),
                "entity_type": r["entity_type"],
                "title": r["title"],
                "content_preview": r["content_preview"],
                "score": r["score"],
            }
            for r in results
        ]

    async def _audit(self, artifact: ContextArtifact, pillar_hint, duration_ms: int) -> None:
        self.db.add(
            ContextBuilds(
                id=artifact.build_id,
                principal_id=artifact.principal_id,
                goal=artifact.goal,
                pillar_hint=pillar_hint,
                budget_tokens=artifact.budget_tokens,
                served=[
                    {"path": s.path, "kind": s.kind, "tokens": s.tokens, "reason": s.reason,
                     "similarity": round(s.similarity, 3)}
                    for s in artifact.sections
                ],
                skills_served=[
                    {"path": s.path, "full_body": s.full_body is not None}
                    for s in artifact.skills
                ],
                fallback_used=bool(artifact.fallback),
                coverage=artifact.coverage,
                artifact_tokens=artifact.tokens_used,
                duration_ms=duration_ms,
            )
        )
        await self.db.commit()


async def get_build(db: AsyncSession, build_id: uuid.UUID) -> ContextBuilds | None:
    return (
        await db.execute(select(ContextBuilds).where(ContextBuilds.id == build_id))
    ).scalar_one_or_none()
