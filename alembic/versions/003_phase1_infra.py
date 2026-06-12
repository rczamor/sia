"""Phase 1 infrastructure: HNSW indexes, job queue schema, RRF config, plugin registry.

- Creates the four HNSW embedding indexes that were declared in the ORM but never
  migrated (a migration-built database seq-scanned every dense search).
- Applies the procrastinate job-queue schema (durable jobs in Postgres).
- Replaces the weighted-sum `hybrid_search` config with RRF `retrieval` config.
- Adds provider selection to llm_* configs; registers llm/embeddings plugins.
- Drops `plugins.credentials` — secrets live in the environment, never the DB.

Revision ID: 003
Revises: 002
Create Date: 2026-06-12
"""

from importlib.resources import files
from typing import Sequence, Union

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

HNSW_TABLES = ["source_content", "my_thoughts", "expertise_artifacts", "consolidations"]


def upgrade() -> None:
    # 1. HNSW embedding indexes (defect #3 in ALIGNMENT.md)
    for table in HNSW_TABLES:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_embedding ON {table} "
            f"USING hnsw (embedding vector_cosine_ops) "
            f"WITH (m = 16, ef_construction = 64)"
        )

    # 2. Procrastinate job-queue schema (bundled with the installed library version).
    # The schema is multi-statement SQL; asyncpg's prepared-statement path can't run
    # it, so it goes through a direct psycopg connection (procrastinate's own driver).
    schema_sql = files("procrastinate.sql").joinpath("schema.sql").read_text()
    dsn = op.get_bind().engine.url.render_as_string(hide_password=False).replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    import psycopg

    with psycopg.connect(dsn) as conn:
        conn.execute(schema_sql)

    # 3. Retrieval config: RRF replaces weighted-sum score mixing
    op.execute("DELETE FROM ai_config WHERE config_key = 'hybrid_search'")
    op.execute(
        """
        INSERT INTO ai_config (config_key, config_value, description) VALUES
        ('retrieval',
         '{"rrf_k": 60, "candidates_per_table": 50}',
         'Hybrid retrieval: Reciprocal Rank Fusion constant and per-table candidate depth')
        ON CONFLICT (config_key) DO NOTHING
        """
    )

    # 4. Operation-level provider selection
    op.execute(
        """
        UPDATE ai_config
        SET config_value = config_value || '{"provider": "anthropic"}'::jsonb
        WHERE config_key LIKE 'llm_%' AND NOT config_value ? 'provider'
        """
    )

    # 5. Plugin registry: llm + embeddings plugins; enable the defaults
    op.execute(
        """
        INSERT INTO plugins (id, display_name, category, enabled) VALUES
        ('anthropic', 'Anthropic Claude', 'llm', true),
        ('openrouter', 'OpenRouter', 'llm', false),
        ('ollama', 'Ollama Embeddings', 'embeddings', true)
        ON CONFLICT (id) DO NOTHING
        """
    )

    # 6. Secrets never live in the database
    op.execute("ALTER TABLE plugins DROP COLUMN IF EXISTS credentials")


def downgrade() -> None:
    raise NotImplementedError("Phase 1 infrastructure is foundational; restore from backup.")
