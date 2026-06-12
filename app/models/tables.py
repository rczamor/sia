import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SourceContent(Base):
    __tablename__ = "source_content"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text, unique=True)
    content: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    pillar: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    source_type: Mapped[str] = mapped_column(String(50), default="article")
    author: Mapped[str | None] = mapped_column(Text)
    your_highlights: Mapped[str | None] = mapped_column(Text)
    your_notes: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    embedding = mapped_column(Vector(768), nullable=True)
    search_vector = mapped_column(TSVECTOR, nullable=True)
    is_consolidated: Mapped[bool] = mapped_column(Boolean, default=False)
    trust_tier: Mapped[str] = mapped_column(String(20), default="untrusted")
    quarantined: Mapped[bool] = mapped_column(Boolean, default=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_source_content_embedding", "embedding", postgresql_using="hnsw",
              postgresql_with={"m": 16, "ef_construction": 64},
              postgresql_ops={"embedding": "vector_cosine_ops"}),
        Index("ix_source_content_search", "search_vector", postgresql_using="gin"),
        Index("ix_source_content_pillar", "pillar", postgresql_using="gin"),
        Index("ix_source_content_source_type", "source_type"),
        Index("ix_source_content_consolidated", "is_consolidated"),
        Index("ix_source_content_trust", "trust_tier", "quarantined"),
    )


class MyThoughts(Base):
    __tablename__ = "my_thoughts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    pillar: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    thought_type: Mapped[str] = mapped_column(String(50), default="idea")
    related_source_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), default=list
    )
    maturity: Mapped[str] = mapped_column(String(50), default="raw")
    embedding = mapped_column(Vector(768), nullable=True)
    search_vector = mapped_column(TSVECTOR, nullable=True)
    is_consolidated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_my_thoughts_embedding", "embedding", postgresql_using="hnsw",
              postgresql_with={"m": 16, "ef_construction": 64},
              postgresql_ops={"embedding": "vector_cosine_ops"}),
        Index("ix_my_thoughts_search", "search_vector", postgresql_using="gin"),
        Index("ix_my_thoughts_pillar", "pillar", postgresql_using="gin"),
    )


class ExpertiseArtifacts(Base):
    __tablename__ = "expertise_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(50), default="framework")
    domain: Mapped[str | None] = mapped_column(Text)
    pillar: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    embedding = mapped_column(Vector(768), nullable=True)
    search_vector = mapped_column(TSVECTOR, nullable=True)
    is_consolidated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_expertise_artifacts_embedding", "embedding", postgresql_using="hnsw",
              postgresql_with={"m": 16, "ef_construction": 64},
              postgresql_ops={"embedding": "vector_cosine_ops"}),
        Index("ix_expertise_artifacts_search", "search_vector", postgresql_using="gin"),
        Index("ix_expertise_artifacts_pillar", "pillar", postgresql_using="gin"),
    )


class Consolidations(Base):
    __tablename__ = "consolidations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    insight_text: Mapped[str] = mapped_column(Text, nullable=False)
    connected_source_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), default=list
    )
    connected_thought_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), default=list
    )
    pillar: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    consolidation_type: Mapped[str] = mapped_column(String(50), default="connection")
    embedding = mapped_column(Vector(768), nullable=True)
    search_vector = mapped_column(TSVECTOR, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_consolidations_embedding", "embedding", postgresql_using="hnsw",
              postgresql_with={"m": 16, "ef_construction": 64},
              postgresql_ops={"embedding": "vector_cosine_ops"}),
        Index("ix_consolidations_search", "search_vector", postgresql_using="gin"),
        Index("ix_consolidations_pillar", "pillar", postgresql_using="gin"),
    )


class ContentVersions(Base):
    __tablename__ = "content_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    diff_from_previous: Mapped[dict | None] = mapped_column(JSONB)
    change_reason: Mapped[str | None] = mapped_column(Text)
    change_type: Mapped[str] = mapped_column(String(50), default="create")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_content_versions_entity", "entity_type", "entity_id"),
        Index("ix_content_versions_unique", "entity_type", "entity_id", "version_number",
              unique=True),
    )


class ProcessLineage(Base):
    __tablename__ = "process_lineage"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    build_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    principal_id: Mapped[str | None] = mapped_column(String(100))
    input_content_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), default=list
    )
    input_context_summary: Mapped[str | None] = mapped_column(Text)
    prompt_name: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100))
    model_params: Mapped[dict | None] = mapped_column(JSONB)
    langfuse_trace_id: Mapped[str | None] = mapped_column(String(255))
    reasoning_compressed: Mapped[dict | None] = mapped_column(JSONB)
    output_entity_type: Mapped[str | None] = mapped_column(String(50))
    output_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    output_summary: Mapped[str | None] = mapped_column(Text)
    quality_score: Mapped[float | None] = mapped_column(Float)
    engagement_outcome: Mapped[dict | None] = mapped_column(JSONB)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    token_count_input: Mapped[int | None] = mapped_column(Integer)
    token_count_output: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_process_lineage_operation", "operation_type"),
        Index("ix_process_lineage_created", "created_at"),
        Index("ix_process_lineage_output", "output_entity_type", "output_entity_id"),
        Index("ix_process_lineage_prompt", "prompt_name", "prompt_version"),
        Index("ix_process_lineage_quality", "quality_score"),
    )


class ContextSections(Base):
    """Postgres index of the git-backed context store. Files are canonical; this
    table is rebuilt from the store and exists for similarity search and joins."""

    __tablename__ = "context_sections"

    path: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    pillar: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="active")
    priority: Mapped[float] = mapped_column(Float, default=0.5)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    visibility: Mapped[str] = mapped_column(String(10), default="private")
    freshness: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gist: Mapped[str | None] = mapped_column(Text)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)
    embedding = mapped_column(Vector(768), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_context_sections_kind", "kind"),
        Index("ix_context_sections_pillar", "pillar"),
        Index("ix_context_sections_embedding", "embedding", postgresql_using="hnsw",
              postgresql_with={"m": 16, "ef_construction": 64},
              postgresql_ops={"embedding": "vector_cosine_ops"}),
    )


class ConsolidationRuns(Base):
    __tablename__ = "consolidation_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clock: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running")
    input_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), default=list
    )
    files_changed: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    branch: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_consolidation_runs_clock", "clock", "started_at"),
    )


class Entities(Base):
    __tablename__ = "entities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), default="concept")
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    embedding = mapped_column(Vector(768), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_entities_name", "name", unique=True),
    )


class ContextEdges(Base):
    """Knowledge-graph edges. Refs are namespaced strings: ``topic:<path>``,
    ``skill:<path>``, ``entity:<uuid>``, ``source:<uuid>``, ``thought:<uuid>``,
    ``artifact:<uuid>``. Predicates: mentions, supports, contradicts, supersedes,
    related_to, derived_from, requires_skill."""

    __tablename__ = "context_edges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_ref: Mapped[str] = mapped_column(Text, nullable=False)
    predicate: Mapped[str] = mapped_column(String(30), nullable=False)
    object_ref: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    provenance: Mapped[str] = mapped_column(String(30), default="extracted")
    created_by_run: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_context_edges_subject", "subject_ref", "predicate"),
        Index("ix_context_edges_object", "object_ref", "predicate"),
        Index("ix_context_edges_unique", "subject_ref", "predicate", "object_ref", unique=True),
    )


class Principals(Base):
    """Who may consume context: owner, per-purpose agents, anonymous visitors.
    API keys are stored as sha256 hashes only."""

    __tablename__ = "principals"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    token_budget: Mapped[int] = mapped_column(Integer, default=8000)
    allowed_visibilities: Mapped[list[str]] = mapped_column(ARRAY(String), default=lambda: ["public"])
    allow_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    api_key_hash: Mapped[str | None] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_principals_key", "api_key_hash"),
    )


class ContextBuilds(Base):
    """Audit row for every context build — who asked, what was served, how it scored."""

    __tablename__ = "context_builds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    principal_id: Mapped[str] = mapped_column(String(100), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    pillar_hint: Mapped[str | None] = mapped_column(String(50))
    budget_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    served: Mapped[list] = mapped_column(JSONB, default=list)
    skills_served: Mapped[list] = mapped_column(JSONB, default=list)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    coverage: Mapped[float | None] = mapped_column(Float)
    context_score: Mapped[float | None] = mapped_column(Float)
    artifact_tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    flags: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_context_builds_principal", "principal_id", "created_at"),
    )


class AiConfig(Base):
    __tablename__ = "ai_config"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    config_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    config_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Plugins(Base):
    __tablename__ = "plugins"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(50), default="inactive")
    last_health_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


