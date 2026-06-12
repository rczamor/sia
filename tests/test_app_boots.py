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


def test_templates_and_static_are_package_relative():
    """Packaging fix: assets resolve relative to the app package, not the cwd, so
    `import app.main` works when pip-installed / run from any directory."""
    from app.templating import STATIC_DIR, TEMPLATES_DIR

    assert (TEMPLATES_DIR / "base.html").is_file()
    assert (STATIC_DIR / "js" / "json-form.js").is_file()
    # both live under the app package directory
    import app

    pkg_dir = __import__("pathlib").Path(app.__file__).resolve().parent
    assert pkg_dir in TEMPLATES_DIR.parents or TEMPLATES_DIR.parent == pkg_dir


async def test_security_headers_include_csp(anon_client):
    response = await anon_client.get("/api/health")
    csp = response.headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert "object-src 'none'" in csp


async def test_graph_endpoint_respects_limit(client, db_session, store):
    response = await client.get("/api/context/graph?limit=5")
    assert response.status_code == 200
    assert len(response.json()["nodes"]) <= 5 + 5  # capped sections + capped entities


def test_admin_assets_are_vendored():
    """Supply-chain: the admin UI must not load scripts or stylesheets from
    third-party origins — all assets ship in app/static/vendor at pinned versions."""
    import re

    from app.templating import STATIC_DIR, TEMPLATES_DIR

    external = []
    for path in TEMPLATES_DIR.rglob("*.html"):
        for tag in re.findall(r"<(?:script|link)\b[^>]*>", path.read_text()):
            if re.search(r'(?:src|href)="https?://', tag):
                external.append(f"{path.name}: {tag}")
    assert not external, f"templates load external assets: {external}"

    for asset in ("pico.min.css", "htmx.min.js", "cytoscape.min.js"):
        vendored = STATIC_DIR / "vendor" / asset
        assert vendored.is_file() and vendored.stat().st_size > 10_000, asset


async def test_csp_allows_no_third_party_origins(anon_client):
    csp = (await anon_client.get("/api/health")).headers["content-security-policy"]
    assert "script-src 'self';" in csp
    assert "http" not in csp  # no external origin anywhere in the policy


async def test_vendored_assets_are_served(client):
    for asset in ("vendor/pico.min.css", "vendor/htmx.min.js", "vendor/cytoscape.min.js"):
        response = await client.get(f"/static/{asset}")
        assert response.status_code == 200, asset


async def test_rendered_admin_pages_load_no_cdn(client):
    """Rendered output (not just template source) must reference no CDN origin."""
    for page in ("/admin/dashboard", "/admin/graph", "/login"):
        response = await client.get(page)
        assert response.status_code == 200, page
        for origin in ("https://cdn.jsdelivr.net", "https://unpkg.com"):
            assert origin not in response.text, f"{page} references {origin}"


def test_vendored_assets_match_pinned_hashes():
    """No silent vendor-asset upgrades: every file matches the manifest pin."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    try:
        from verify_vendor_assets import verify
    finally:
        sys.path.pop(0)
    assert verify() == []
