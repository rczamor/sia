"""Bypass ledger: record when a consumer used a source outside Sia.

Makes "is Sia the first stop?" measurable and surfaces coverage gaps.

Revision ID: 008
Revises: 007
Create Date: 2026-06-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "context_bypasses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            primary_key=True,
        ),
        sa.Column("principal_id", sa.String(100), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("source", sa.String(500), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_context_bypasses_principal", "context_bypasses", ["principal_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_context_bypasses_principal", "context_bypasses")
    op.drop_table("context_bypasses")
