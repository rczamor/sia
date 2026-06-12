"""Entity-extraction upgrades + change-detection.

- entities: confidence, updated_at, mention_count (alias support already present).
- context_edges: label — the specific relation phrase for entity<->entity edges
  (structural edges leave it null).
- context_sections: content_hash — lets the indexer skip unchanged files (fixes
  the REM "re-gist everything" churn and the re-embed-everything cost).

Revision ID: 007
Revises: 006
Create Date: 2026-06-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "entities",
        sa.Column("confidence", sa.Float(), server_default="0.5", nullable=False),
    )
    op.add_column(
        "entities",
        sa.Column("mention_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "entities",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # Semantic-dedup index: nearest existing entity by embedding.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_entities_embedding ON entities "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )

    op.add_column("context_edges", sa.Column("label", sa.Text(), nullable=True))

    op.add_column("context_sections", sa.Column("content_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("context_sections", "content_hash")
    op.drop_column("context_edges", "label")
    op.execute("DROP INDEX IF EXISTS ix_entities_embedding")
    op.drop_column("entities", "updated_at")
    op.drop_column("entities", "mention_count")
    op.drop_column("entities", "confidence")
