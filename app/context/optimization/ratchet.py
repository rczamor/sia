"""The autoresearch ratchet: parameter optimization that can only move forward.

Opt-in (the ``autoresearch`` plugin row is disabled by default). One iteration:
1. propose a candidate value for a tunable parameter,
2. score the system with the candidate applied (regression pass rate + mean
   coverage over the golden fixtures — measured, not vibes),
3. keep the candidate only if it strictly beats the incumbent; otherwise revert.

Every iteration is recorded in ai_config under ``autoresearch_log`` so the
trajectory is auditable. Promotion is explicit: the candidate writes to the live
ai_config key only on a win.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.builder import ContextBuilder
from app.context.quality import run_regression
from app.context.store.gitstore import GitContextStore
from app.models.tables import AiConfig
from app.providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)

# Tunables the ratchet may touch, with proposal neighborhoods.
TUNABLES: dict[str, dict[str, Any]] = {
    "retrieval.rrf_k": {"candidates": [20, 40, 60, 80, 120]},
    "retrieval.candidates_per_table": {"candidates": [25, 50, 75, 100]},
}


@dataclass
class RatchetResult:
    parameter: str
    incumbent: Any
    candidate: Any
    incumbent_score: float
    candidate_score: float
    promoted: bool


class Ratchet:
    def __init__(self, db: AsyncSession, store: GitContextStore, embedder: EmbeddingProvider):
        self.db = db
        self.store = store
        self.embedder = embedder

    async def _objective(self) -> float:
        """Regression pass rate + mean coverage over the golden fixtures. The builder
        is given a SearchService so the retrieval tunables this ratchet mutates
        (rrf_k, candidates_per_table, min_similarity) actually affect the score —
        otherwise every candidate scores identically and nothing ever promotes."""
        from app.retrieval.search import SearchService

        builder = ContextBuilder(
            self.db, self.store, self.embedder,
            search_service=SearchService(self.db, self.embedder),
        )
        results = await run_regression(self.db, self.store, builder)
        if not results:
            return 0.0
        pass_rate = sum(1 for r in results if r.passed) / len(results)
        mean_coverage = sum(r.coverage for r in results) / len(results)
        return 0.7 * pass_rate + 0.3 * mean_coverage

    async def _get_config(self, key: str) -> dict:
        row = (
            await self.db.execute(select(AiConfig).where(AiConfig.config_key == key))
        ).scalar_one_or_none()
        return dict(row.config_value) if row else {}

    async def _set_config_field(self, key: str, field: str, value: Any) -> None:
        row = (
            await self.db.execute(select(AiConfig).where(AiConfig.config_key == key))
        ).scalar_one_or_none()
        if row is None:
            return
        updated = dict(row.config_value)
        updated[field] = value
        row.config_value = updated
        await self.db.flush()

    async def iterate(self, parameter: str) -> RatchetResult:
        if parameter not in TUNABLES:
            raise ValueError(f"Unknown tunable: {parameter}")
        config_key, field = parameter.split(".", 1)
        current_config = await self._get_config(config_key)
        incumbent = current_config.get(field)

        candidates = [c for c in TUNABLES[parameter]["candidates"] if c != incumbent]
        if not candidates:
            raise ValueError(f"No candidates for {parameter}")

        incumbent_score = await self._objective()

        best_candidate, best_score = None, incumbent_score
        for candidate in candidates:
            await self._set_config_field(config_key, field, candidate)
            score = await self._objective()
            if score > best_score:
                best_candidate, best_score = candidate, score

        promoted = best_candidate is not None
        # Explicit promote-or-revert: the live key ends at the winner.
        await self._set_config_field(
            config_key, field, best_candidate if promoted else incumbent
        )
        await self._log(parameter, incumbent, best_candidate, incumbent_score, best_score)
        await self.db.commit()

        return RatchetResult(
            parameter=parameter,
            incumbent=incumbent,
            candidate=best_candidate,
            incumbent_score=incumbent_score,
            candidate_score=best_score,
            promoted=promoted,
        )

    async def _log(self, parameter, incumbent, candidate, incumbent_score, candidate_score):
        row = (
            await self.db.execute(
                select(AiConfig).where(AiConfig.config_key == "autoresearch_log")
            )
        ).scalar_one_or_none()
        entry = {
            "at": datetime.now(timezone.utc).isoformat(),
            "parameter": parameter,
            "incumbent": incumbent,
            "candidate": candidate,
            "incumbent_score": round(incumbent_score, 4),
            "candidate_score": round(candidate_score, 4),
            "promoted": candidate is not None,
        }
        if row is None:
            self.db.add(
                AiConfig(
                    config_key="autoresearch_log",
                    config_value={"iterations": [entry]},
                    description="Autoresearch ratchet history (append-only)",
                )
            )
        else:
            updated = dict(row.config_value)
            updated["iterations"] = (updated.get("iterations") or [])[-49:] + [entry]
            row.config_value = updated
        await self.db.flush()
