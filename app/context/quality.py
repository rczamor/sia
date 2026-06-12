"""Context quality: the context_score on every build, and the regression suite.

context_score is the pre-inference quality measure the thesis calls for — it judges
the *context*, not the model output:
- coverage: how well the consolidated store matched the goal (max topic similarity)
- freshness: token-weighted freshness decay of what was served
- consolidation: fraction of served tokens that came from consolidated storage
  rather than raw fallback
- grounding: fraction of served topics whose claims carry citations

Regression fixtures live in the store at .sia/regression/*.yaml:
    goal: "..."
    expect_paths: ["knowledge/..."]
    min_coverage: 0.3
"""

from dataclasses import dataclass

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.builder import ContextArtifact, ContextBuilder
from app.context.index import freshness_decay
from app.context.principals import Principal
from app.context.store.documents import estimate_tokens
from app.context.store.gitstore import GitContextStore
from app.models.tables import ContextBuilds, ContextSections

COVERAGE_WEIGHT = 0.35
FRESHNESS_WEIGHT = 0.25
CONSOLIDATION_WEIGHT = 0.20
GROUNDING_WEIGHT = 0.20

REGRESSION_PREFIX = ".sia/regression/"

OWNER_FOR_REGRESSION = Principal(
    id="owner", kind="owner", token_budget=12000,
    allowed_visibilities=("public", "private"), allow_fallback=True,
)


@dataclass
class ContextScore:
    coverage: float
    freshness: float
    consolidation: float
    grounding: float

    @property
    def composite(self) -> float:
        return (
            COVERAGE_WEIGHT * self.coverage
            + FRESHNESS_WEIGHT * self.freshness
            + CONSOLIDATION_WEIGHT * self.consolidation
            + GROUNDING_WEIGHT * self.grounding
        )

    def to_dict(self) -> dict:
        return {
            "coverage": round(self.coverage, 3),
            "freshness": round(self.freshness, 3),
            "consolidation": round(self.consolidation, 3),
            "grounding": round(self.grounding, 3),
            "composite": round(self.composite, 3),
        }


async def score_artifact(db: AsyncSession, artifact: ContextArtifact) -> ContextScore:
    served_tokens = 0
    freshness_weighted = 0.0
    grounded_topics = 0
    topic_count = 0

    for section in artifact.sections:
        row = await db.get(ContextSections, section.path)
        decay = freshness_decay(row.freshness) if row else 0.5
        served_tokens += section.tokens
        freshness_weighted += decay * section.tokens
        if section.kind == "topic":
            topic_count += 1
            if "[source:" in section.content or "[thought:" in section.content:
                grounded_topics += 1

    fallback_tokens = sum(
        estimate_tokens(str(item.get("content_preview") or "")) for item in artifact.fallback
    )
    total_tokens = served_tokens + fallback_tokens

    score = ContextScore(
        coverage=min(1.0, artifact.coverage),
        freshness=(freshness_weighted / served_tokens) if served_tokens else 0.0,
        consolidation=(served_tokens / total_tokens) if total_tokens else 0.0,
        grounding=(grounded_topics / topic_count) if topic_count else 0.0,
    )

    build = await db.get(ContextBuilds, artifact.build_id)
    if build is not None:
        build.context_score = score.composite
        flags = dict(build.flags or {})
        flags["score_components"] = score.to_dict()
        build.flags = flags
        await db.commit()
    return score


@dataclass
class RegressionResult:
    fixture: str
    goal: str
    passed: bool
    missing_paths: list[str]
    coverage: float
    min_coverage: float


async def run_regression(
    db: AsyncSession, store: GitContextStore, builder: ContextBuilder
) -> list[RegressionResult]:
    """Run every golden goal->paths fixture against the live store + builder."""
    results: list[RegressionResult] = []
    for path in await store.list_paths(prefix=REGRESSION_PREFIX):
        if not path.endswith((".yaml", ".yml")):
            continue
        raw = await store.read(path)
        if not raw:
            continue
        fixture = yaml.safe_load(raw) or {}
        goal = fixture.get("goal")
        if not goal:
            continue
        expected = fixture.get("expect_paths") or []
        min_coverage = float(fixture.get("min_coverage", 0.0))

        artifact = await builder.build(goal=goal, principal=OWNER_FOR_REGRESSION)
        served = {s.path for s in artifact.sections} | {s.path for s in artifact.skills}
        missing = [p for p in expected if p not in served]
        results.append(
            RegressionResult(
                fixture=path,
                goal=goal,
                passed=not missing and artifact.coverage >= min_coverage,
                missing_paths=missing,
                coverage=artifact.coverage,
                min_coverage=min_coverage,
            )
        )
    return results
