"""Builder + principals: context_builds audit, principal registry, lineage linkage.

Revision ID: 005
Revises: 004
Create Date: 2026-06-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "principals",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),  # owner|agent|visitor
        sa.Column("token_budget", sa.Integer(), nullable=False, server_default="8000"),
        sa.Column(
            "allowed_visibilities",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{public}",
        ),
        sa.Column("allow_fallback", sa.Boolean(), nullable=False, server_default="false"),
        # sha256 hex of the API key; the key itself is shown once at creation
        sa.Column("api_key_hash", sa.String(64)),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_principals_key", "principals", ["api_key_hash"])

    op.execute(
        """
        INSERT INTO principals
            (id, display_name, kind, token_budget, allowed_visibilities, allow_fallback)
        VALUES
            ('owner', 'Owner', 'owner', 12000, '{public,private}', true),
            ('visitor', 'Public visitor', 'visitor', 2500, '{public}', false)
        """
    )

    op.create_table(
        "context_builds",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            primary_key=True,
        ),
        sa.Column("principal_id", sa.String(100), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("pillar_hint", sa.String(50)),
        sa.Column("budget_tokens", sa.Integer(), nullable=False),
        sa.Column("served", postgresql.JSONB(), server_default="[]"),
        sa.Column("skills_served", postgresql.JSONB(), server_default="[]"),
        sa.Column("fallback_used", sa.Boolean(), server_default="false"),
        sa.Column("coverage", sa.Float()),
        sa.Column("context_score", sa.Float()),
        sa.Column("artifact_tokens", sa.Integer(), server_default="0"),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("flags", postgresql.JSONB(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_context_builds_principal", "context_builds", ["principal_id", "created_at"])

    op.add_column("process_lineage", sa.Column("build_id", postgresql.UUID(as_uuid=True)))
    op.add_column("process_lineage", sa.Column("principal_id", sa.String(100)))
    op.create_index("ix_process_lineage_build", "process_lineage", ["build_id"])


def downgrade() -> None:
    op.drop_index("ix_process_lineage_build", "process_lineage")
    op.drop_column("process_lineage", "principal_id")
    op.drop_column("process_lineage", "build_id")
    op.drop_table("context_builds")
    op.drop_table("principals")
