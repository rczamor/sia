"""Deny-by-default sweep + principal/key lifecycle + login flow."""

from app.context.principals import PrincipalService

PUBLIC_OK = [
    ("/api/health", 200),
    ("/login", 200),
]


async def test_public_paths_are_reachable(anon_client):
    for path, expected in PUBLIC_OK:
        response = await anon_client.get(path)
        assert response.status_code == expected, path


async def test_deny_by_default_sweep(anon_client):
    """Every registered route must refuse anonymous access unless explicitly public."""
    from app.gateway.authn import PUBLIC_PREFIXES, VISITOR_PATHS
    from app.main import app

    failures = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if not path or "{" in path:
            continue
        if path.startswith(PUBLIC_PREFIXES) or path in VISITOR_PATHS or path == "/":
            continue
        method = "GET" if "GET" in methods else next(iter(methods), "GET")
        response = await anon_client.request(method, path)
        if response.status_code not in (401, 303, 405):
            failures.append(f"{method} {path} -> {response.status_code}")
    assert not failures, "Routes reachable without auth:\n" + "\n".join(failures)


async def test_build_audit_endpoints_require_auth(anon_client):
    """/api/context/builds must NOT be swept in by the visitor prefix for
    /api/context/build (the cross-anonymous build-audit leak)."""
    for path in ("/api/context/builds", "/api/context/builds/00000000-0000-0000-0000-000000000000"):
        response = await anon_client.get(path)
        assert response.status_code == 401, f"{path} reachable anonymously: {response.status_code}"


async def test_admin_redirects_anonymous_to_login(anon_client):
    response = await anon_client.get("/admin")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


async def test_login_sets_cookie_and_grants_admin(anon_client):
    response = await anon_client.post(
        "/login", data={"email": "admin@test.local", "password": "test-password"}
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin"
    assert "sia_session" in response.headers.get("set-cookie", "")
    assert "HttpOnly" in response.headers["set-cookie"]

    follow = await anon_client.get("/admin")  # cookie persisted on the client
    assert follow.status_code == 200


async def test_login_rejects_bad_password(anon_client):
    response = await anon_client.post(
        "/login", data={"email": "admin@test.local", "password": "wrong"}
    )
    assert response.status_code == 303
    assert "error" in response.headers["location"]


async def test_visitor_can_build_anonymously(anon_client, db_session, fake_runtime):
    response = await anon_client.post("/api/context/build", json={"goal": "what is sia"})
    assert response.status_code == 200
    body = response.json()
    assert body["principal"] == "visitor"
    assert body["fallback_unconsolidated"] == []


async def test_agent_key_lifecycle(client, anon_client, db_session, fake_runtime):
    # owner creates an agent principal
    created = await client.post(
        "/api/principals",
        json={"purpose": "research", "token_budget": 4000},
    )
    assert created.status_code == 201
    api_key = created.json()["api_key"]
    assert api_key.startswith("sia_")

    # the key authenticates a build with the agent's identity
    response = await anon_client.post(
        "/api/context/build",
        json={"goal": "reciprocal rank fusion"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 200
    assert response.json()["principal"] == "agent-research"

    # rotation invalidates the old key
    rotated = await client.post("/api/principals/agent-research/rotate")
    new_key = rotated.json()["api_key"]
    old = await anon_client.post(
        "/api/context/build",
        json={"goal": "x y z"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    # old key falls back to visitor on the public build path
    assert old.json()["principal"] == "visitor"

    fresh = await anon_client.post(
        "/api/context/build",
        json={"goal": "x y z"},
        headers={"Authorization": f"Bearer {new_key}"},
    )
    assert fresh.json()["principal"] == "agent-research"

    # revocation kills access entirely
    await client.delete("/api/principals/agent-research")
    revoked = await anon_client.get(
        "/api/knowledge/sources", headers={"Authorization": f"Bearer {new_key}"}
    )
    assert revoked.status_code == 401


async def test_agent_cannot_touch_owner_surface(client, anon_client, db_session):
    created = await client.post("/api/principals", json={"purpose": "limited"})
    api_key = created.json()["api_key"]
    headers = {"Authorization": f"Bearer {api_key}"}
    # config, principal admin, and the raw data layer are all owner-only
    for path in ("/api/config/", "/api/knowledge/thoughts", "/api/knowledge/search?q=x"):
        response = await anon_client.get(path, headers=headers)
        assert response.status_code == 403, f"{path} reachable by agent: {response.status_code}"
    ingest = await anon_client.post(
        "/api/ingest/thought", json={"content": "agent write"}, headers=headers
    )
    assert ingest.status_code == 403


async def test_agent_cannot_read_admin_visualizations(client, anon_client, db_session):
    """Graph/health/runs read across the whole store without per-principal visibility
    filtering, so a public-only agent key must not reach them (would leak private
    topic/skill/entity structure)."""
    created = await client.post("/api/principals", json={"purpose": "snoop"})
    api_key = created.json()["api_key"]
    for path in ("/api/context/graph", "/api/context/health", "/api/context/runs"):
        response = await anon_client.get(path, headers={"Authorization": f"Bearer {api_key}"})
        assert response.status_code == 403, path


async def test_principals_admin_is_owner_only(anon_client):
    response = await anon_client.get("/api/principals")
    assert response.status_code == 401


async def test_key_hashes_only_in_database(client, db_session):
    from sqlalchemy import text

    created = await client.post("/api/principals", json={"purpose": "hashcheck"})
    api_key = created.json()["api_key"]
    stored = (
        await db_session.execute(
            text("SELECT api_key_hash FROM principals WHERE id = 'agent-hashcheck'")
        )
    ).scalar()
    assert stored != api_key
    assert len(stored) == 64  # sha256 hex
    service = PrincipalService(db_session)
    principal = await service.authenticate(api_key)
    assert principal and principal.id == "agent-hashcheck"


async def test_secure_cookie_and_hsts_by_default(http_anon_client):
    """Production posture by default: even when uvicorn sees plain http (TLS proxy
    not forwarding the scheme), the session cookie is Secure and HSTS is sent."""
    response = await http_anon_client.post(
        "/login", data={"email": "admin@test.local", "password": "test-password"}
    )
    assert response.status_code == 303
    set_cookie = response.headers["set-cookie"]
    assert "Secure" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "strict-transport-security" in response.headers
    assert "max-age=63072000" in response.headers["strict-transport-security"]


async def test_forwarded_proto_login_still_secure(http_anon_client):
    """An internal http request carrying X-Forwarded-Proto: https (proxy headers
    not trusted by uvicorn, so the scheme stays http) still gets a Secure cookie —
    cookie security must not depend on header plumbing."""
    response = await http_anon_client.post(
        "/login",
        data={"email": "admin@test.local", "password": "test-password"},
        headers={"X-Forwarded-Proto": "https"},
    )
    assert response.status_code == 303
    assert "Secure" in response.headers["set-cookie"]


async def test_local_dev_can_disable_secure_and_hsts(http_anon_client, monkeypatch):
    """The plain-http override is deliberate and works: no Secure flag (a non-
    localhost http browser would drop the cookie) and no HSTS."""
    from app.config import settings

    monkeypatch.setattr(settings, "session_cookie_secure", False)
    monkeypatch.setattr(settings, "hsts_enabled", False)
    response = await http_anon_client.post(
        "/login", data={"email": "admin@test.local", "password": "test-password"}
    )
    assert response.status_code == 303
    assert "Secure" not in response.headers["set-cookie"]
    assert "strict-transport-security" not in response.headers


async def test_logout_deletes_cookie_with_matching_flags(client):
    """The expiring Set-Cookie must carry the same attributes as the one set at
    login, so deletion targets the identical cookie in every browser."""
    response = await client.get("/logout")
    assert response.status_code == 303
    set_cookie = response.headers["set-cookie"]
    assert 'sia_session=""' in set_cookie or "sia_session=;" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Secure" in set_cookie  # matches session_cookie_secure default
    assert "Max-Age=0" in set_cookie or "expires=" in set_cookie.lower()
