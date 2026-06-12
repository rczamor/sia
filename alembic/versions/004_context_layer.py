"""Context layer: trust tiers, store index, consolidation runs, knowledge graph.

- source_content gains trust_tier + quarantined (memory-poisoning defense: intake
  is tiered, untrusted-derived store writes go through a reviewed branch).
- context_sections: Postgres index of the git-backed context store (files stay
  canonical; this table is rebuildable from the store).
- consolidation_runs: audit of every clock run.
- entities + context_edges: the knowledge graph as plain tables — subject/predicate/
  object rows traversed with recursive CTEs. No graph database.

Revision ID: 004
Revises: 003
Create Date: 2026-06-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Trust tiers on intake
    op.add_column(
        "source_content",
        sa.Column("trust_tier", sa.String(20), server_default="untrusted", nullable=False),
    )
    op.add_column(
        "source_content",
        sa.Column("quarantined", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_index("ix_source_content_trust", "source_content", ["trust_tier", "quarantined"])

    # 2. Store index (rebuildable from the file store)
    op.create_table(
        "context_sections",
        sa.Column("path", sa.Text(), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),  # topic|skill|profile|thesis|tension
        sa.Column("title", sa.Text()),
        sa.Column("pillar", sa.String(50)),
        sa.Column("status", sa.String(20), server_default="active"),
        sa.Column("priority", sa.Float(), server_default="0.5"),
        sa.Column("confidence", sa.Float(), server_default="0.5"),
        sa.Column("visibility", sa.String(10), server_default="private"),
        sa.Column("freshness", sa.DateTime(timezone=True)),
        sa.Column("gist", sa.Text()),
        sa.Column("token_estimate", sa.Integer(), server_default="0"),
        sa.Column("embedding", Vector(768)),
        sa.Column("commit_sha", sa.String(64)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_context_sections_kind", "context_sections", ["kind"])
    op.create_index("ix_context_sections_pillar", "context_sections", ["pillar"])
    op.execute(
        "CREATE INDEX ix_context_sections_embedding ON context_sections "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )

    # 3. Consolidation run audit
    op.create_table(
        "consolidation_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            primary_key=True,
        ),
        sa.Column("clock", sa.String(20), nullable=False),  # light|rem|deep
        sa.Column("status", sa.String(20), server_default="running"),
        sa.Column("input_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True))),
        sa.Column("files_changed", postgresql.ARRAY(sa.Text())),
        sa.Column("branch", sa.Text()),
        sa.Column("summary", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("cost_usd", sa.Float(), server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_consolidation_runs_clock", "consolidation_runs", ["clock", "started_at"])

    # 4. Knowledge graph: entities + typed edges
    op.create_table(
        "entities",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            primary_key=True,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.String(50), server_default="concept"),
        sa.Column("aliases", postgresql.ARRAY(sa.Text()), server_default="{}"),
        sa.Column("embedding", Vector(768)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_entities_name", "entities", ["name"], unique=True)

    op.create_table(
        "context_edges",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            primary_key=True,
        ),
        # refs are namespaced strings: "topic:knowledge/x.md", "skill:skills/y/SKILL.md",
        # "entity:<uuid>", "source:<uuid>", "thought:<uuid>", "artifact:<uuid>"
        sa.Column("subject_ref", sa.Text(), nullable=False),
        sa.Column("predicate", sa.String(30), nullable=False),
        sa.Column("object_ref", sa.Text(), nullable=False),
        sa.Column("weight", sa.Float(), server_default="1.0"),
        sa.Column("provenance", sa.String(30), server_default="extracted"),
        sa.Column("created_by_run", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_context_edges_subject", "context_edges", ["subject_ref", "predicate"])
    op.create_index("ix_context_edges_object", "context_edges", ["object_ref", "predicate"])
    op.create_index(
        "ix_context_edges_unique",
        "context_edges",
        ["subject_ref", "predicate", "object_ref"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("context_edges")
    op.drop_table("entities")
    op.drop_table("consolidation_runs")
    op.drop_table("context_sections")
    op.drop_index("ix_source_content_trust", "source_content")
    op.drop_column("source_content", "quarantined")
    op.drop_column("source_content", "trust_tier")
