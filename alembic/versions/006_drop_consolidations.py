"""Drop the legacy consolidations table.

The Context layer's consolidated storage is the git-backed file store (topics,
skills, tensions) indexed in context_sections; the row-shaped consolidations table
was schema-only (zero writers ever) and is superseded.

Revision ID: 006
Revises: 005
Create Date: 2026-06-12
"""

from typing import Sequence, Union

from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS consolidations_search_trigger ON consolidations")
    op.execute("DROP FUNCTION IF EXISTS consolidations_search_update()")
    op.execute("DROP TABLE IF EXISTS consolidations")


def downgrade() -> None:
    raise NotImplementedError("consolidations was schema-only; nothing to restore.")
