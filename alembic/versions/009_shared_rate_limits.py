"""Shared rate-limit ledger.

Login and anonymous visitor-build limits need to be consistent across app
instances. Store only hashed client keys, and keep the table small with the
middleware's rolling cleanup.

Revision ID: 009
Revises: 008
Create Date: 2026-06-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_hits",
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("hit_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_rate_limit_hits_scope_key_time",
        "rate_limit_hits",
        ["scope", "key_hash", "hit_at"],
    )
    op.create_index("ix_rate_limit_hits_hit_at", "rate_limit_hits", ["hit_at"])


def downgrade() -> None:
    op.drop_index("ix_rate_limit_hits_hit_at", "rate_limit_hits")
    op.drop_index("ix_rate_limit_hits_scope_key_time", "rate_limit_hits")
    op.drop_table("rate_limit_hits")
