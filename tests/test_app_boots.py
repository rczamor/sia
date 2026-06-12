async def test_health(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "sia"}


async def test_admin_dashboard_renders(client):
    response = await client.get("/admin")
    assert response.status_code == 200
    assert "Sia" in response.text


async def test_admin_ingest_page_renders(client):
    response = await client.get("/admin/ingest")
    assert response.status_code == 200


async def test_admin_knowledge_page_renders(client):
    response = await client.get("/admin/knowledge")
    assert response.status_code == 200


async def test_publishing_tables_are_gone(db_session):
    from sqlalchemy import text

    for table in ("generated_posts", "experiments", "output_templates"):
        result = await db_session.execute(
            text("SELECT to_regclass(:name)"), {"name": f"public.{table}"}
        )
        assert result.scalar() is None, f"{table} should have been dropped by migration 002"


async def test_publishing_plugin_rows_are_gone(db_session):
    from sqlalchemy import text

    result = await db_session.execute(text("SELECT id FROM plugins ORDER BY id"))
    ids = [row[0] for row in result]
    assert "linkedin" not in ids
    assert "x" not in ids
    assert "feedly" in ids  # ingestion plugins survive
