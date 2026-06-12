"""Composition root: builds configured services from the plugin registry.

Both entry processes (the FastAPI app and the procrastinate worker) call
``get_runtime()``; the first call discovers entry-point plugins, reads enablement
from the ``plugins`` table, and initializes the enabled ones. Operation-level LLM
selection (which provider/model handles classification vs consolidation) comes from
``ai_config`` rows of the shape ``llm_<operation>: {"provider": ..., "model": ...}``.
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.builder import ContextArtifact, ContextBuilder
from app.context.consolidation.deep import DeepClock
from app.context.consolidation.light import LightClock
from app.context.consolidation.rem import RemClock
from app.context.index import StoreIndexer
from app.context.review import ReviewService
from app.context.store.gitstore import GitContextStore
from app.data.ingestion import IngestionService
from app.data.lineage import LineageService, TrackedLLMProvider
from app.models.enums import PluginCategory
from app.models.tables import AiConfig, Plugins
from app.plugins.base import PluginManager
from app.plugins.llmops.noop import NoOpLLMOps
from app.providers.base import EmbeddingProvider, LLMOpsProvider, LLMProvider
from app.retrieval.search import SearchService

logger = logging.getLogger(__name__)

DEFAULT_LLM_PLUGIN = "anthropic"
DEFAULT_EMBEDDINGS_PLUGIN = "ollama"


class Runtime:
    def __init__(self, plugins: PluginManager, llm_configs: dict[str, dict[str, Any]]):
        self.plugins = plugins
        self._llm_configs = llm_configs
        self.context_store = GitContextStore()

    # --- provider resolution ---

    def llm_for(self, operation: str) -> tuple[LLMProvider, dict[str, Any]]:
        """Resolve (provider, model params) for an internal LLM operation."""
        config = self._llm_configs.get(f"llm_{operation}") or self._llm_configs.get(
            "llm_default", {}
        )
        plugin_id = config.get("provider", DEFAULT_LLM_PLUGIN)
        plugin = self.plugins.get(plugin_id)
        if plugin is None or plugin.category != PluginCategory.LLM:
            available = self.plugins.get_by_category(PluginCategory.LLM)
            if not available:
                raise RuntimeError(
                    f"No LLM plugin available for operation {operation!r} "
                    f"(wanted {plugin_id!r}). Check API keys and plugin enablement."
                )
            plugin = available[0]
            logger.warning(
                "LLM plugin %r unavailable for %r; falling back to %r",
                plugin_id, operation, plugin.plugin_id,
            )
        params = {k: v for k, v in config.items() if k != "provider"}
        return plugin.provider, params

    @property
    def embedder(self) -> EmbeddingProvider:
        plugin = self.plugins.get(DEFAULT_EMBEDDINGS_PLUGIN)
        if plugin is None:
            available = self.plugins.get_by_category(PluginCategory.EMBEDDINGS)
            if not available:
                raise RuntimeError("No embeddings plugin available")
            plugin = available[0]
        return plugin.provider

    @property
    def llmops(self) -> LLMOpsProvider:
        enabled = self.plugins.get_by_category(PluginCategory.LLMOPS)
        return enabled[0].provider if enabled else NoOpLLMOps()

    # --- service factories ---

    def ingestion_service(self, db: AsyncSession) -> IngestionService:
        provider, params = self.llm_for("classification")
        tracked = TrackedLLMProvider(provider, LineageService(db), llmops=self.llmops)
        return IngestionService(db, tracked, self.embedder, classify_params=params)

    def search_service(self, db: AsyncSession) -> SearchService:
        return SearchService(db, self.embedder)

    def _consolidation_llm(self, db: AsyncSession) -> tuple[TrackedLLMProvider, dict[str, Any]]:
        provider, params = self.llm_for("consolidation")
        return TrackedLLMProvider(provider, LineageService(db), llmops=self.llmops), params

    def light_clock(self, db: AsyncSession) -> LightClock:
        llm, params = self._consolidation_llm(db)
        return LightClock(db, self.context_store, llm, self.embedder, llm_params=params)

    def rem_clock(self, db: AsyncSession) -> RemClock:
        llm, params = self._consolidation_llm(db)
        return RemClock(db, self.context_store, llm, self.embedder, llm_params=params)

    def deep_clock(self, db: AsyncSession) -> DeepClock:
        llm, params = self._consolidation_llm(db)
        return DeepClock(db, self.context_store, llm, self.embedder, llm_params=params)

    def indexer(self, db: AsyncSession) -> StoreIndexer:
        return StoreIndexer(db, self.context_store, self.embedder)

    def context_builder(self, db: AsyncSession) -> ContextBuilder:
        return ContextBuilder(
            db, self.context_store, self.embedder, search_service=self.search_service(db)
        )

    async def build_context(
        self,
        db: AsyncSession,
        goal: str,
        principal,
        budget_tokens: int | None = None,
        pillar_hint: str | None = None,
    ) -> ContextArtifact:
        """Build + score: every build gets a context_score and an LLM-ops trace."""
        from app.context.quality import score_artifact

        artifact = await self.context_builder(db).build(
            goal=goal, principal=principal, budget_tokens=budget_tokens, pillar_hint=pillar_hint
        )
        score = await score_artifact(db, artifact)
        trace_id = await self.llmops.trace(
            name="context_build",
            input_data={"goal": goal, "principal": principal.id},
            output_data=score.to_dict(),
            metadata={"build_id": str(artifact.build_id)},
        )
        if trace_id:
            await self.llmops.score(trace_id, "context_score", score.composite)
        return artifact

    def review_service(self, db: AsyncSession) -> ReviewService:
        return ReviewService(db, self.context_store, self.embedder)


_runtime: Runtime | None = None


async def get_runtime() -> Runtime:
    # No lock: the lifespan/worker initializes once before traffic; a benign double
    # init under a race just builds the same registry twice. (An asyncio.Lock here
    # would bind to the first event loop and break test isolation.)
    global _runtime
    if _runtime is not None:
        return _runtime

    from sqlalchemy.exc import ProgrammingError

    from app.database import async_session

    try:
        async with async_session() as db:
            rows = (await db.execute(select(Plugins).where(Plugins.enabled))).scalars().all()
            enabled = {row.id: dict(row.config or {}) for row in rows}
            config_rows = (await db.execute(select(AiConfig))).scalars().all()
            llm_configs = {
                row.config_key: dict(row.config_value)
                for row in config_rows
                if row.config_key.startswith("llm_")
            }
    except ProgrammingError as exc:
        # The plugins/ai_config tables don't exist yet — the database hasn't been
        # migrated. Give an actionable message instead of a raw UndefinedTable.
        raise RuntimeError(
            "Database is not migrated (core tables missing). Run "
            "`alembic upgrade head` (or `make migrate`) before starting. "
            "Docker users: the engine entrypoint migrates automatically."
        ) from exc

    manager = PluginManager()
    await manager.initialize_enabled(enabled)
    logger.info("Plugins initialized: %s", sorted(manager.all))
    _runtime = Runtime(manager, llm_configs)
    return _runtime


async def shutdown_runtime() -> None:
    global _runtime
    if _runtime is not None:
        await _runtime.plugins.shutdown_all()
        _runtime = None


def reset_runtime_for_tests() -> None:
    global _runtime
    _runtime = None
