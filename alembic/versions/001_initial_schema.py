"""Initial schema with all tables

Revision ID: 001
Revises:
Create Date: 2026-04-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import ProgrammingError

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extensions. Managed Postgres (Neon, RDS, ...) and locked-down roles often
    # can't run CREATE EXTENSION: skip it when the extension is already installed,
    # and turn a permission failure into an actionable message instead of a raw
    # InsufficientPrivilege mid-migration.
    bind = op.get_bind()
    for ext in ("vector", "uuid-ossp"):
        installed = bind.execute(
            sa.text("SELECT 1 FROM pg_extension WHERE extname = :name"), {"name": ext}
        ).scalar()
        if installed:
            continue
        try:
            op.execute(f'CREATE EXTENSION IF NOT EXISTS "{ext}"')
        except ProgrammingError as exc:
            raise RuntimeError(
                f"This database role cannot create the '{ext}' extension. Enable it "
                f"once as a superuser (CREATE EXTENSION \"{ext}\";) or via your "
                "managed-Postgres console, then re-run `alembic upgrade head`."
            ) from exc

    # --- source_content ---
    op.create_table(
        "source_content",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), unique=True),
        sa.Column("content", sa.Text()),
        sa.Column("summary", sa.Text()),
        sa.Column("pillar", postgresql.ARRAY(sa.String())),
        sa.Column("source_type", sa.String(50), server_default="article"),
        sa.Column("author", sa.Text()),
        sa.Column("your_highlights", sa.Text()),
        sa.Column("your_notes", sa.Text()),
        sa.Column("tags", postgresql.ARRAY(sa.String())),
        sa.Column("embedding", Vector(768)),
        sa.Column("search_vector", postgresql.TSVECTOR()),
        sa.Column("is_consolidated", sa.Boolean(), server_default="false"),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_source_content_pillar", "source_content", ["pillar"], postgresql_using="gin")
    op.create_index("ix_source_content_search", "source_content", ["search_vector"], postgresql_using="gin")
    op.create_index("ix_source_content_source_type", "source_content", ["source_type"])
    op.create_index("ix_source_content_consolidated", "source_content", ["is_consolidated"])

    # tsvector trigger for source_content
    op.execute("""
        CREATE OR REPLACE FUNCTION source_content_search_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector := to_tsvector('english', coalesce(NEW.title, '') || ' ' || coalesce(NEW.summary, '') || ' ' || coalesce(NEW.content, ''));
            NEW.updated_at := now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER source_content_search_trigger
        BEFORE INSERT OR UPDATE ON source_content
        FOR EACH ROW EXECUTE FUNCTION source_content_search_update();
    """)

    # --- my_thoughts ---
    op.create_table(
        "my_thoughts",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("pillar", postgresql.ARRAY(sa.String())),
        sa.Column("thought_type", sa.String(50), server_default="idea"),
        sa.Column("related_source_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True))),
        sa.Column("maturity", sa.String(50), server_default="raw"),
        sa.Column("embedding", Vector(768)),
        sa.Column("search_vector", postgresql.TSVECTOR()),
        sa.Column("is_consolidated", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_my_thoughts_pillar", "my_thoughts", ["pillar"], postgresql_using="gin")
    op.create_index("ix_my_thoughts_search", "my_thoughts", ["search_vector"], postgresql_using="gin")

    op.execute("""
        CREATE OR REPLACE FUNCTION my_thoughts_search_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector := to_tsvector('english', coalesce(NEW.content, ''));
            NEW.updated_at := now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER my_thoughts_search_trigger
        BEFORE INSERT OR UPDATE ON my_thoughts
        FOR EACH ROW EXECUTE FUNCTION my_thoughts_search_update();
    """)

    # --- expertise_artifacts ---
    op.create_table(
        "expertise_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("artifact_type", sa.String(50), server_default="framework"),
        sa.Column("domain", sa.Text()),
        sa.Column("pillar", postgresql.ARRAY(sa.String())),
        sa.Column("embedding", Vector(768)),
        sa.Column("search_vector", postgresql.TSVECTOR()),
        sa.Column("is_consolidated", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_expertise_artifacts_pillar", "expertise_artifacts", ["pillar"], postgresql_using="gin")
    op.create_index("ix_expertise_artifacts_search", "expertise_artifacts", ["search_vector"], postgresql_using="gin")

    op.execute("""
        CREATE OR REPLACE FUNCTION expertise_artifacts_search_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector := to_tsvector('english', coalesce(NEW.title, '') || ' ' || coalesce(NEW.content, ''));
            NEW.updated_at := now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER expertise_artifacts_search_trigger
        BEFORE INSERT OR UPDATE ON expertise_artifacts
        FOR EACH ROW EXECUTE FUNCTION expertise_artifacts_search_update();
    """)

    # --- consolidations ---
    op.create_table(
        "consolidations",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("insight_text", sa.Text(), nullable=False),
        sa.Column("connected_source_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True))),
        sa.Column("connected_thought_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True))),
        sa.Column("pillar", postgresql.ARRAY(sa.String())),
        sa.Column("confidence", sa.Float(), server_default="0.0"),
        sa.Column("consolidation_type", sa.String(50), server_default="connection"),
        sa.Column("embedding", Vector(768)),
        sa.Column("search_vector", postgresql.TSVECTOR()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_consolidations_pillar", "consolidations", ["pillar"], postgresql_using="gin")
    op.create_index("ix_consolidations_search", "consolidations", ["search_vector"], postgresql_using="gin")

    op.execute("""
        CREATE OR REPLACE FUNCTION consolidations_search_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector := to_tsvector('english', coalesce(NEW.insight_text, ''));
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER consolidations_search_trigger
        BEFORE INSERT OR UPDATE ON consolidations
        FOR EACH ROW EXECUTE FUNCTION consolidations_search_update();
    """)

    # --- generated_posts ---
    op.create_table(
        "generated_posts",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("channel", sa.String(50), server_default="linkedin"),
        sa.Column("template_id", postgresql.UUID(as_uuid=True)),
        sa.Column("pillar", postgresql.ARRAY(sa.String())),
        sa.Column("hook_style", sa.String(100)),
        sa.Column("source_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True))),
        sa.Column("thought_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True))),
        sa.Column("consolidation_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True))),
        sa.Column("experiment_id", postgresql.UUID(as_uuid=True)),
        sa.Column("langfuse_prompt_version", sa.String(100)),
        sa.Column("fact_check_status", sa.String(50), server_default="pending"),
        sa.Column("fact_check_details", postgresql.JSONB()),
        sa.Column("quality_score", sa.Float()),
        sa.Column("quality_details", postgresql.JSONB()),
        sa.Column("status", sa.String(50), server_default="draft"),
        sa.Column("platform_post_id", sa.String(255)),
        sa.Column("impressions", sa.Integer(), server_default="0"),
        sa.Column("engagement_rate", sa.Float(), server_default="0.0"),
        sa.Column("likes", sa.Integer(), server_default="0"),
        sa.Column("comments", sa.Integer(), server_default="0"),
        sa.Column("shares", sa.Integer(), server_default="0"),
        sa.Column("bookmarks", sa.Integer(), server_default="0"),
        sa.Column("embedding", Vector(768)),
        sa.Column("search_vector", postgresql.TSVECTOR()),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_generated_posts_status", "generated_posts", ["status"])
    op.create_index("ix_generated_posts_channel", "generated_posts", ["channel"])
    op.create_index("ix_generated_posts_pillar", "generated_posts", ["pillar"], postgresql_using="gin")

    # --- experiments ---
    op.create_table(
        "experiments",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("variable", sa.Text(), nullable=False),
        sa.Column("variant_a", sa.Text(), nullable=False),
        sa.Column("variant_b", sa.Text(), nullable=False),
        sa.Column("status", sa.String(50), server_default="active"),
        sa.Column("result_summary", sa.Text()),
        sa.Column("winner", sa.String(10)),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("concluded_at", sa.DateTime(timezone=True)),
    )

    # --- content_versions ---
    op.create_table(
        "content_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("diff_from_previous", postgresql.JSONB()),
        sa.Column("change_reason", sa.Text()),
        sa.Column("change_type", sa.String(50), server_default="create"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_content_versions_entity", "content_versions", ["entity_type", "entity_id"])
    op.create_index("ix_content_versions_unique", "content_versions", ["entity_type", "entity_id", "version_number"], unique=True)

    # --- process_lineage ---
    op.create_table(
        "process_lineage",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("operation_type", sa.String(50), nullable=False),
        sa.Column("input_content_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True))),
        sa.Column("input_context_summary", sa.Text()),
        sa.Column("prompt_name", sa.String(100)),
        sa.Column("prompt_version", sa.String(50)),
        sa.Column("model", sa.String(100)),
        sa.Column("model_params", postgresql.JSONB()),
        sa.Column("langfuse_trace_id", sa.String(255)),
        sa.Column("reasoning_compressed", postgresql.JSONB()),
        sa.Column("output_entity_type", sa.String(50)),
        sa.Column("output_entity_id", postgresql.UUID(as_uuid=True)),
        sa.Column("output_summary", sa.Text()),
        sa.Column("quality_score", sa.Float()),
        sa.Column("engagement_outcome", postgresql.JSONB()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("token_count_input", sa.Integer()),
        sa.Column("token_count_output", sa.Integer()),
        sa.Column("cost_usd", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_process_lineage_operation", "process_lineage", ["operation_type"])
    op.create_index("ix_process_lineage_created", "process_lineage", ["created_at"])
    op.create_index("ix_process_lineage_output", "process_lineage", ["output_entity_type", "output_entity_id"])
    op.create_index("ix_process_lineage_prompt", "process_lineage", ["prompt_name", "prompt_version"])
    op.create_index("ix_process_lineage_quality", "process_lineage", ["quality_score"])

    # --- ai_config ---
    op.create_table(
        "ai_config",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("config_key", sa.String(100), unique=True, nullable=False),
        sa.Column("config_value", postgresql.JSONB(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- plugins ---
    op.create_table(
        "plugins",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false"),
        sa.Column("config", postgresql.JSONB(), server_default="{}"),
        sa.Column("credentials", postgresql.JSONB(), server_default="{}"),
        sa.Column("status", sa.String(50), server_default="inactive"),
        sa.Column("last_health_check", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- output_templates ---
    op.create_table(
        "output_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("target_channels", postgresql.ARRAY(sa.String())),
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column("variables", postgresql.JSONB(), server_default="{}"),
        sa.Column("constraints", postgresql.JSONB(), server_default="{}"),
        sa.Column("example_output", sa.Text()),
        sa.Column("schedule_slot", sa.String(50)),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- Seed data: ai_config defaults ---
    op.execute("""
        INSERT INTO ai_config (config_key, config_value, description) VALUES
        ('llm_default', '{"model": "claude-sonnet-4-5-20250929", "temperature": 0.7, "max_tokens": 4096}', 'Default LLM settings for general use'),
        ('llm_classification', '{"model": "claude-haiku-4-5-20251001", "temperature": 0.3, "max_tokens": 1024}', 'LLM settings for classification tasks'),
        ('llm_consolidation', '{"model": "claude-sonnet-4-5-20250929", "temperature": 0.8, "max_tokens": 8192}', 'LLM settings for consolidation agent'),
        ('embedding', '{"provider": "ollama", "model": "nomic-embed-text", "dimensions": 768}', 'Embedding model configuration'),
        ('hybrid_search', '{"semantic_weight": 0.7, "keyword_weight": 0.3, "similarity_threshold": 0.3, "max_results": 20}', 'Hybrid search weight configuration'),
        ('consolidation', '{"interval_hours": 6, "min_items": 3, "max_items": 20}', 'Consolidation schedule configuration')
    """)

    # --- Seed data: plugins registry ---
    op.execute("""
        INSERT INTO plugins (id, display_name, category, enabled) VALUES
        ('linkedin', 'LinkedIn', 'publishing', false),
        ('x', 'X (Twitter)', 'publishing', false),
        ('feedly', 'Feedly', 'ingestion', false),
        ('slack', 'Slack', 'ingestion', false),
        ('langfuse', 'Langfuse', 'llmops', false),
        ('autoresearch', 'Autoresearch (Karpathy Loop)', 'optimization', false)
    """)

    # --- Seed data: default output templates ---
    op.execute("""
        INSERT INTO output_templates (name, description, target_channels, prompt_template, constraints, schedule_slot) VALUES
        ('Short Contrarian Take', 'Provocative, opinionated claim that challenges conventional wisdom', '{"linkedin","x"}',
         'Write a short, contrarian take about {{topic}}. Start with a bold claim that challenges conventional wisdom. Support with one concrete example or data point. End with a question or reframe. Voice: authoritative, direct, practitioner-first.',
         '{"min_words": 150, "max_words": 250, "tone": "contrarian"}', 'monday'),
        ('Signal', 'React to news/tool/paper through Context Intelligence lens', '{"linkedin","x"}',
         'React to this development: {{topic}}. Analyze through the Context Intelligence lens. What does this mean for practitioners? What are most people missing? Voice: analytical, forward-looking.',
         '{"min_words": 200, "max_words": 400, "tone": "analytical"}', 'tuesday'),
        ('Deep Dive', 'Teach something specific with real examples and architecture details', '{"linkedin"}',
         'Write a deep dive about {{topic}}. Structure: hook, problem statement, architecture/approach, real example with specifics, key takeaway. Voice: authoritative teacher, show depth.',
         '{"min_words": 700, "max_words": 1000, "tone": "educational"}', 'wednesday'),
        ('Framework', 'Package a reusable decision framework or rubric', '{"linkedin","x"}',
         'Create a practical framework for {{topic}}. Structure: the problem this solves, the framework (3-5 steps/questions), how to apply it, one example. Voice: practical, reusable.',
         '{"min_words": 400, "max_words": 700, "tone": "practical"}', 'thursday'),
        ('Story', 'Personal narrative connecting experience to insight', '{"linkedin","x"}',
         'Tell a story about {{topic}}. Start with a specific moment. Build the narrative with honest details. Connect to a broader lesson. Voice: warm, vulnerable, insightful.',
         '{"min_words": 300, "max_words": 600, "tone": "narrative"}', 'friday')
    """)


def downgrade() -> None:
    op.drop_table("output_templates")
    op.drop_table("plugins")
    op.drop_table("ai_config")
    op.drop_table("process_lineage")
    op.drop_table("content_versions")
    op.drop_table("experiments")
    op.drop_table("generated_posts")
    op.execute("DROP TRIGGER IF EXISTS consolidations_search_trigger ON consolidations")
    op.execute("DROP FUNCTION IF EXISTS consolidations_search_update()")
    op.drop_table("consolidations")
    op.execute("DROP TRIGGER IF EXISTS expertise_artifacts_search_trigger ON expertise_artifacts")
    op.execute("DROP FUNCTION IF EXISTS expertise_artifacts_search_update()")
    op.drop_table("expertise_artifacts")
    op.execute("DROP TRIGGER IF EXISTS my_thoughts_search_trigger ON my_thoughts")
    op.execute("DROP FUNCTION IF EXISTS my_thoughts_search_update()")
    op.drop_table("my_thoughts")
    op.execute("DROP TRIGGER IF EXISTS source_content_search_trigger ON source_content")
    op.execute("DROP FUNCTION IF EXISTS source_content_search_update()")
    op.drop_table("source_content")
