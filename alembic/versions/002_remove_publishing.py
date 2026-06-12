"""Remove publishing/distribution tables — Sia is a context engine, not a content tool.

Drops generated_posts, experiments, output_templates and the publishing plugin
registry rows. Run scripts/archive_publishing.py against the target database first.

Revision ID: 002
Revises: 001
Create Date: 2026-06-11
"""

from typing import Sequence, Union

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS generated_posts")
    op.execute("DROP TABLE IF EXISTS experiments")
    op.execute("DROP TABLE IF EXISTS output_templates")
    op.execute("DELETE FROM plugins WHERE id IN ('linkedin', 'x')")


def downgrade() -> None:
    raise NotImplementedError(
        "Publishing tables are intentionally removed; restore from the JSON archive "
        "produced by scripts/archive_publishing.py if ever needed."
    )
