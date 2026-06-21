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

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.graph import GraphService, file_ref
from app.context.store.documents import MarkdownSerializer
from app.context.store.gitstore import GitContextStore
from app.data.lineage import TrackedLLMProvider
from app.models.tables import ContextSections, Entities
from app.prompts.consolidation import DEEP_ENTITIES
from app.providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)

# Cosine similarity above which two names are treated as one entity. Deliberately
# high: a semantic match is NOT persisted as an alias (see resolve_or_create), so a
# borderline false match is re-evaluated each call rather than fused forever — only
# LLM-declared aliases are persisted.
ENTITY_MERGE_THRESHOLD = 0.92
ENTITY_BATCH_SIZE = 25  # topics per extraction LLM call (covers the whole store in batches)


@dataclass
class ResolvedEntity:
    id: uuid.UUID
    name: str
    created: bool
    # canonical name + the declared aliases actually attached to THIS entity; the
    # extractor maps only these surface forms to this id (a rejected/claimed alias
    # is excluded, so relations never resolve to the wrong node)
    forms: list[str]


class EntityService:
    def __init__(self, db: AsyncSession, embedder: EmbeddingProvider):
        self.db = db
        self.embedder = embedder

    async def resolve_or_create(
        self,
        name: str,
        entity_type: str = "concept",
        confidence: float = 0.5,
        aliases: list[str] | None = None,
    ) -> ResolvedEntity | None:
        """Return the canonical entity for ``name``, creating or alias-merging as
        needed. ``aliases`` are surface forms (acronyms, expansions) the caller
        already knows belong to this entity — they are attached to the resolved
        entity AND indexed so future lookups of those forms resolve here. Returns
        None for empty names."""
        name = (name or "").strip()
        if not name:
            return None
        declared = [a.strip() for a in (aliases or []) if a and a.strip() and a.strip() != name]

        entity = await self._find(name, entity_type)
        if entity is None:
            entity = Entities(
                name=name,
                entity_type=entity_type,
                embedding=await self.embedder.embed(name),
                aliases=[],
                confidence=confidence,
                mention_count=0,
            )
            self.db.add(entity)
            created = True
        else:
            created = False
            # NOTE: a semantic/alias-resolved queried form is NOT auto-persisted as an
            # alias — only explicit declared aliases are. This keeps a borderline
            # semantic match from fusing two concepts permanently in the alias index.

        # Attach only the declared aliases that this entity may legitimately claim;
        # `attached` is the subset actually recorded (clash-free).
        attached = await self._add_aliases(entity, declared)
        await self._reinforce(entity, confidence)
        await self.db.flush()
        return ResolvedEntity(entity.id, entity.name, created=created, forms=[entity.name, *attached])

    async def _find(self, name: str, entity_type: str) -> Entities | None:
        """Locate an existing entity by exact name, then alias, then embedding
        similarity (same type). Returns None if genuinely new."""
        # 1. exact name
        existing = (
            await self.db.execute(select(Entities).where(Entities.name == name))
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        # 2. alias match. At most one entity may hold a given alias (enforced by the
        # clash check in _add_aliases), so the result is deterministic; ORDER BY id
        # guards against any legacy duplicate.
        alias_hit = (
            await self.db.execute(
                select(Entities).where(Entities.aliases.any(name)).order_by(Entities.id).limit(1)
            )
        ).scalar_one_or_none()
        if alias_hit is not None:
            return alias_hit

        # 3. semantic match: nearest same-type entity above threshold. A degenerate
        # (zero) embedding yields a NaN distance; the >= test then fails closed.
        embedding = await self.embedder.embed(name)
        if not any(embedding):
            return None
        near = (
            await self.db.execute(
                text(
                    """
                    SELECT id, 1 - (embedding <=> CAST(:vec AS vector)) AS sim
                    FROM entities
                    WHERE entity_type = :etype AND embedding IS NOT NULL
                    ORDER BY embedding <=> CAST(:vec AS vector)
                    LIMIT 1
                    """
                ),
                {"vec": str([float(v) for v in embedding]), "etype": entity_type},
            )
        ).mappings().first()
        if near is not None and near["sim"] is not None and float(near["sim"]) >= ENTITY_MERGE_THRESHOLD:
            return await self.db.get(Entities, near["id"])
        return None

    async def _add_aliases(self, entity: Entities, aliases: list[str]) -> list[str]:
        """Attach surface forms to ``entity`` unless one already names OR aliases a
        *different* entity (avoid stealing another node's identity). Returns the
        aliases actually attached."""
        current = list(entity.aliases or [])
        attached: list[str] = []
        for alias in aliases:
            if alias == entity.name or alias in current:
                continue
            clash = (
                await self.db.execute(
                    select(Entities.id).where(
                        Entities.id != entity.id,
                        or_(Entities.name == alias, Entities.aliases.any(alias)),
                    )
                )
            ).first()
            if clash is None:
                current.append(alias)
                attached.append(alias)
        entity.aliases = current
        return attached

    @staticmethod
    async def _reinforce(entity: Entities, confidence: float) -> None:
        """Repeated extraction of the same entity raises its confidence (capped) and
        its mention count — salience from demonstrated recurrence."""
        entity.mention_count = (entity.mention_count or 0) + 1
        entity.confidence = min(1.0, max(entity.confidence or 0.0, confidence) + 0.05)

    async def find_by_name_or_alias(self, name: str) -> uuid.UUID | None:
        """Type-independent lookup of an existing entity by exact name or alias.
        No create, no semantic match — used to resolve relation endpoints."""
        name = (name or "").strip()
        if not name:
            return None
        row = (
            await self.db.execute(
                select(Entities.id)
                .where(or_(Entities.name == name, Entities.aliases.any(name)))
                .order_by(Entities.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        return row

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
        """gist :: key claims for one topic, read FRESH from the store file (not the
        possibly-stale ORM row, which may predate this run's re-gist)."""
        content = await self.store.read(row.path)
        if not content:
            return f"{row.gist or ''} :: "
        document = self.serializer.loads(row.path, content)
        gist = document.section("Gist") or (row.gist or "")
        claims = " ".join(document.section("Key claims").split())
        return f"{gist} :: {claims[:1500]}"

    async def extract_for_topics(self, rows: list[ContextSections], run_id) -> int:
        """Extract entities/relations for the given topics. Returns new-entity count."""
        known_paths = {r.path for r in rows}
        new_entities = 0
        for start in range(0, len(rows), ENTITY_BATCH_SIZE):
            batch = rows[start : start + ENTITY_BATCH_SIZE]
            lines = []
            for row in batch:
                lines.append(f"- {row.path} :: {await self._topic_text(row)}")
            prompt_template = await self.llm.prompt("deep_entities", DEEP_ENTITIES)
            response = await self.llm.complete_structured(
                messages=[
                    {
                        "role": "user",
                        "content": prompt_template.format(topics="\n".join(lines)),
                    }
                ],
                schema={"entities": [], "relations": []},
                operation_type="consolidate",
                prompt_name="deep_entities",
                **self.llm_params,
            )
            new_entities += await self._apply(response, known_paths, run_id)
        return new_entities

    async def _apply(self, response: dict, known_paths: set[str], run_id) -> int:
        new_entities = 0
        # map every surface form (name + declared aliases) to the resolved id so
        # relations reference the canonical entity, not a wrongly-typed duplicate
        name_to_id: dict[str, uuid.UUID] = {}
        for item in response.get("entities") or []:
            aliases = item.get("aliases") or []
            resolved = await self.entities.resolve_or_create(
                name=item.get("name", ""),
                entity_type=item.get("type", "concept"),
                aliases=aliases,  # attached to this entity, not re-resolved separately
            )
            if resolved is None:
                continue
            new_entities += int(resolved.created)
            # map only the forms this entity authoritatively owns (canonical name +
            # aliases actually attached) — a rejected/claimed alias is excluded, so a
            # relation never resolves to the wrong node
            for form in resolved.forms:
                form = (form or "").strip()
                if form and form not in name_to_id:
                    name_to_id[form] = resolved.id
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
        """Resolve a relation endpoint to an EXISTING entity (this batch's map, then
        a type-independent exact-name/alias lookup). A relation that names an unknown
        entity is skipped rather than spawning a mistyped phantom node."""
        name = (name or "").strip()
        if not name:
            return None
        if name in name_to_id:
            return f"entity:{name_to_id[name]}"
        existing = await self.entities.find_by_name_or_alias(name)
        if existing is not None:
            name_to_id[name] = existing
            return f"entity:{existing}"
        return None
