"""Entity resolution for the knowledge graph.

Entity extraction (LLM, in the clocks) hands names to this service, which decides
whether a proposed name is a *new* entity or an *alias* of an existing one. Three
matching layers, cheapest first:

1. exact name match;
2. alias match (the name already appears in some entity's aliases[]);
3. semantic match — nearest existing entity of the same type by embedding cosine
   similarity above ENTITY_MERGE_THRESHOLD, in which case the proposed name is
   recorded as an alias rather than fragmenting into a second node.

This closes the "RRF and reciprocal-rank-fusion and Reciprocal Rank Fusion become
three entities" gap; the aliases column and the entity embedding are both load-
bearing here.
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.graph import GraphService, file_ref
from app.context.store.documents import MarkdownSerializer
from app.context.store.gitstore import GitContextStore
from app.data.lineage import TrackedLLMProvider
from app.models.tables import ContextSections, Entities
from app.prompts.consolidation import DEEP_ENTITIES
from app.providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)

ENTITY_MERGE_THRESHOLD = 0.88  # cosine similarity above which two names are one entity
ENTITY_BATCH_SIZE = 25  # topics per extraction LLM call (covers the whole store in batches)


@dataclass
class ResolvedEntity:
    id: uuid.UUID
    name: str
    created: bool


class EntityService:
    def __init__(self, db: AsyncSession, embedder: EmbeddingProvider):
        self.db = db
        self.embedder = embedder

    async def resolve_or_create(
        self,
        name: str,
        entity_type: str = "concept",
        confidence: float = 0.5,
    ) -> ResolvedEntity | None:
        """Return the canonical entity for ``name``, creating or alias-merging as
        needed. Returns None for empty names."""
        name = (name or "").strip()
        if not name:
            return None

        # 1. exact name
        existing = (
            await self.db.execute(select(Entities).where(Entities.name == name))
        ).scalar_one_or_none()
        if existing is not None:
            await self._reinforce(existing, confidence)
            return ResolvedEntity(existing.id, existing.name, created=False)

        # 2. alias match (name already an alias of some entity)
        alias_hit = (
            await self.db.execute(
                select(Entities).where(Entities.aliases.any(name)).limit(1)
            )
        ).scalar_one_or_none()
        if alias_hit is not None:
            await self._reinforce(alias_hit, confidence)
            return ResolvedEntity(alias_hit.id, alias_hit.name, created=False)

        embedding = await self.embedder.embed(name)

        # 3. semantic match: nearest same-type entity above threshold
        near = (
            await self.db.execute(
                text(
                    """
                    SELECT id, name, aliases,
                           1 - (embedding <=> CAST(:vec AS vector)) AS sim
                    FROM entities
                    WHERE entity_type = :etype AND embedding IS NOT NULL
                    ORDER BY embedding <=> CAST(:vec AS vector)
                    LIMIT 1
                    """
                ),
                {"vec": str([float(v) for v in embedding]), "etype": entity_type},
            )
        ).mappings().first()
        if near is not None and float(near["sim"]) >= ENTITY_MERGE_THRESHOLD:
            merged = await self.db.get(Entities, near["id"])
            if name not in (merged.aliases or []):
                merged.aliases = [*(merged.aliases or []), name]
            await self._reinforce(merged, confidence)
            return ResolvedEntity(merged.id, merged.name, created=False)

        # 4. genuinely new
        entity = Entities(
            name=name,
            entity_type=entity_type,
            embedding=embedding,
            confidence=confidence,
            mention_count=1,
        )
        self.db.add(entity)
        await self.db.flush()
        return ResolvedEntity(entity.id, entity.name, created=True)

    @staticmethod
    async def _reinforce(entity: Entities, confidence: float) -> None:
        """Repeated extraction of the same entity raises its confidence (capped) and
        its mention count — salience from demonstrated recurrence."""
        entity.mention_count = (entity.mention_count or 0) + 1
        entity.confidence = min(1.0, max(entity.confidence or 0.0, confidence) + 0.05)

    async def count(self) -> int:
        return (await self.db.execute(select(func.count(Entities.id)))).scalar() or 0


class EntityExtractor:
    """LLM-driven named-entity extraction over topic files, shared by the deep and
    REM clocks. Feeds gist + key claims (not just the gist), batches over every
    topic given (no top-N cap), dedups through EntityService, and writes both
    topic->entity ``mentions`` edges and entity<->entity ``related_to`` edges with
    the specific relation phrase in the edge label."""

    def __init__(
        self,
        db: AsyncSession,
        store: GitContextStore,
        llm: TrackedLLMProvider,
        embedder: EmbeddingProvider,
        llm_params: dict | None = None,
    ):
        self.db = db
        self.store = store
        self.llm = llm
        self.llm_params = llm_params or {}
        self.entities = EntityService(db, embedder)
        self.graph = GraphService(db)
        self.serializer = MarkdownSerializer()

    async def _topic_text(self, row: ContextSections) -> str:
        """gist :: key claims for one topic (claims add the named entities the gist
        omits)."""
        content = await self.store.read(row.path)
        claims = ""
        if content:
            claims = " ".join(self.serializer.loads(row.path, content).section("Key claims").split())
        return f"{row.gist or ''} :: {claims[:1500]}"

    async def extract_for_topics(self, rows: list[ContextSections], run_id) -> int:
        """Extract entities/relations for the given topics. Returns new-entity count."""
        known_paths = {r.path for r in rows}
        new_entities = 0
        for start in range(0, len(rows), ENTITY_BATCH_SIZE):
            batch = rows[start : start + ENTITY_BATCH_SIZE]
            lines = []
            for row in batch:
                lines.append(f"- {row.path} :: {await self._topic_text(row)}")
            response = await self.llm.complete_structured(
                messages=[{"role": "user", "content": DEEP_ENTITIES.format(topics="\n".join(lines))}],
                schema={"entities": [], "relations": []},
                operation_type="consolidate",
                prompt_name="deep_entities",
                **self.llm_params,
            )
            new_entities += await self._apply(response, known_paths, run_id)
        return new_entities

    async def _apply(self, response: dict, known_paths: set[str], run_id) -> int:
        new_entities = 0
        name_to_id: dict[str, uuid.UUID] = {}
        for item in response.get("entities") or []:
            resolved = await self.entities.resolve_or_create(
                name=item.get("name", ""),
                entity_type=item.get("type", "concept"),
            )
            if resolved is None:
                continue
            name_to_id[item.get("name", "").strip()] = resolved.id
            new_entities += int(resolved.created)
            # record surface forms the LLM reported as aliases
            for alias in item.get("aliases") or []:
                await self.entities.resolve_or_create(name=alias, entity_type=item.get("type", "concept"))
            for path in item.get("mentioned_in") or []:
                if path in known_paths:
                    await self.graph.upsert_edge(
                        file_ref(path), "mentions", f"entity:{resolved.id}", run_id=run_id
                    )

        # entity <-> entity relations (typed via the edge label)
        for rel in response.get("relations") or []:
            subj = await self._ref_for(rel.get("subject"), name_to_id)
            obj = await self._ref_for(rel.get("object"), name_to_id)
            relation = (rel.get("relation") or "").strip()
            if subj and obj and subj != obj and relation:
                await self.graph.upsert_edge(
                    subj, "related_to", obj, run_id=run_id, label=relation[:100]
                )
        return new_entities

    async def _ref_for(self, name: str | None, name_to_id: dict[str, uuid.UUID]) -> str | None:
        name = (name or "").strip()
        if not name:
            return None
        if name in name_to_id:
            return f"entity:{name_to_id[name]}"
        resolved = await self.entities.resolve_or_create(name=name)
        if resolved is None:
            return None
        name_to_id[name] = resolved.id
        return f"entity:{resolved.id}"
