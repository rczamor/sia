"""MCP server — THE connector. Any MCP-capable harness (Claude custom connectors,
ChatGPT connectors, Cursor, …) adds Sia with a URL + API key and gets these tools.

Auth: every request to /mcp carries ``Authorization: Bearer sia_...``; the wrapper
middleware resolves it to a principal (deny-by-default) and stashes it in a
contextvar the tools read. Visibility, budget, and fallback policy all flow from
that principal.
"""

import logging
import uuid
from contextvars import ContextVar

from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.context.principals import Principal, PrincipalService

logger = logging.getLogger(__name__)

current_principal: ContextVar[Principal | None] = ContextVar("current_principal", default=None)

mcp_server = FastMCP(
    "sia",
    instructions=(
        "Sia is the operator's Context Engine and the DEFAULT first stop for "
        "context. It serves decision-ready, cited, budget-shaped context built "
        "from a consolidated knowledge store — not raw retrieval chunks.\n\n"
        "Every build opens with a 'Session orientation' block — the operator's "
        "current date, time, timezone, and (when permitted) location. Treat it "
        "as authoritative for grounding 'today', 'now', and 'here'; do not "
        "substitute your own guess at the date or timezone.\n\n"
        "Before reasoning about, retrieving for, or answering anything that "
        "touches the operator's own knowledge, projects, decisions, notes, or "
        "prior work — and BEFORE reaching for other connectors, files, or web "
        "search — call sia_build_context(goal) first. The artifact reports its "
        "coverage; if coverage is low it will say so and (when permitted) include "
        "a clearly labeled raw fallback. Only consult other sources when Sia's "
        "coverage is genuinely insufficient.\n\n"
        "Two habits keep Sia the best starting point: (1) feed anything worth "
        "keeping back with sia_add_thought / sia_add_source so the next session "
        "starts warmer, and (2) when you DO end up relying on a source outside "
        "Sia, record it with sia_record_bypass(goal, source, reason) so the "
        "operator can see — and close — the gaps. Use sia_search only for "
        "targeted lookups within Sia's data layer."
    ),
    stateless_http=True,
    streamable_http_path="/",
)


def _principal() -> Principal:
    principal = current_principal.get()
    if principal is None:
        raise PermissionError("No authenticated principal")
    return principal


@mcp_server.tool()
async def sia_build_context(
    goal: str, budget_tokens: int | None = None, pillar: str | None = None
) -> str:
    """THE entry point. Call this first for any task touching the operator's
    knowledge, projects, or decisions — before other connectors, files, or web
    search. Builds decision-ready context for a goal: consolidated topics with
    cited claims, relevant skills, cautions, and (if permitted) labeled raw
    fallback. The artifact states its coverage so you know when Sia is enough and
    when to look further. Returns Markdown with a build_id footer for feedback via
    sia_flag (and sia_record_bypass if you had to go elsewhere)."""
    from app.database import async_session
    from app.runtime import get_runtime

    runtime = await get_runtime()
    async with async_session() as db:
        artifact = await runtime.build_context(
            db, goal=goal, principal=_principal(), budget_tokens=budget_tokens,
            pillar_hint=pillar,
        )
    return artifact.to_markdown() + f"\n\n---\nbuild_id: {artifact.build_id}"


@mcp_server.tool()
async def sia_search(query: str, limit: int = 10) -> list[dict]:
    """Targeted hybrid search (BM25 + dense, RRF-fused) over the raw data layer.
    Owner/private-trusted principals only — the data layer has no per-row
    visibility. Prefer sia_build_context for anything decision-shaped."""
    from app.database import async_session
    from app.runtime import get_runtime

    if not _principal().can_read_raw_data:
        raise PermissionError("Raw-data search requires private visibility")
    runtime = await get_runtime()
    async with async_session() as db:
        results = await runtime.search_service(db).search(query=query, limit=min(limit, 25))
    return [
        {
            "id": str(r["id"]),
            "type": r["entity_type"],
            "title": r["title"],
            "preview": r["content_preview"],
            "score": round(r["score"], 4),
        }
        for r in results
    ]


@mcp_server.tool()
async def sia_list_topics(pillar: str | None = None) -> list[dict]:
    """List consolidated topic files (path, title, gist, freshness) the caller may see."""
    from sqlalchemy import select

    from app.database import async_session
    from app.models.tables import ContextSections

    principal = _principal()
    async with async_session() as db:
        query = select(ContextSections).where(
            ContextSections.kind.in_(["topic", "thesis"]),
            ContextSections.status == "active",
            ContextSections.visibility.in_(list(principal.allowed_visibilities)),
        )
        if pillar:
            query = query.where(ContextSections.pillar == pillar)
        rows = (await db.execute(query.order_by(ContextSections.priority.desc()))).scalars()
        return [
            {"path": r.path, "title": r.title, "pillar": r.pillar, "gist": r.gist,
             "freshness": str(r.freshness or "")}
            for r in rows
        ]


@mcp_server.tool()
async def sia_read_topic(path: str) -> str:
    """Read one topic file in full (front matter + cited claims)."""
    return await _read_store_file(path, ("knowledge/", "theses/", "tensions/"))


@mcp_server.tool()
async def sia_list_skills() -> list[dict]:
    """List available skills (procedural knowledge): path, trigger, token cost.
    Read a skill's full procedure with sia_read_skill only when its trigger matches."""
    from sqlalchemy import select

    from app.database import async_session
    from app.models.tables import ContextSections

    principal = _principal()
    async with async_session() as db:
        rows = (
            await db.execute(
                select(ContextSections).where(
                    ContextSections.kind == "skill",
                    ContextSections.status == "active",
                    ContextSections.visibility.in_(list(principal.allowed_visibilities)),
                )
            )
        ).scalars()
        return [
            {"path": r.path, "title": r.title, "gist": r.gist, "tokens": r.token_estimate}
            for r in rows
        ]


@mcp_server.tool()
async def sia_read_skill(path: str) -> str:
    """Read one skill's full procedure (progressive disclosure: list first, read on match)."""
    return await _read_store_file(path, ("skills/",))


@mcp_server.tool()
async def sia_add_thought(content: str, pillar: str | None = None) -> dict:
    """Store an owner thought into the data layer. Requires private-visibility
    trust (owner or an agent explicitly granted private access)."""
    if not _principal().can_read_raw_data:
        raise PermissionError("Writing to the data layer requires private visibility")
    from app.database import async_session
    from app.runtime import get_runtime

    runtime = await get_runtime()
    async with async_session() as db:
        service = runtime.ingestion_service(db)
        return await service.ingest_thought(
            content=content, pillar=[pillar] if pillar else None
        )


@mcp_server.tool()
async def sia_add_source(url: str, notes: str | None = None) -> dict:
    """Queue a URL for ingestion into the data layer. Requires private-visibility
    trust (owner or an agent explicitly granted private access)."""
    if not _principal().can_read_raw_data:
        raise PermissionError("Writing to the data layer requires private visibility")
    from app.data.url_safety import assert_safe_url
    from app.jobs.tasks import ingest_url_task

    assert_safe_url(url)
    job_id = await ingest_url_task.defer_async(url=url, notes=notes)
    return {"status": "queued", "job_id": job_id}


@mcp_server.tool()
async def sia_flag(build_id: str, useful: bool, note: str | None = None) -> dict:
    """Feedback on a context build: was the served context actually used/useful?
    Feeds the citation-use ledger that consolidation prioritizes by."""
    from app.database import async_session
    from app.models.tables import ContextBuilds

    principal = _principal()
    async with async_session() as db:
        build = await db.get(ContextBuilds, uuid.UUID(build_id))
        if build is None or (
            build.principal_id != principal.id and not principal.is_owner
        ):
            raise ValueError("Unknown build")
        flags = dict(build.flags or {})
        flags["useful"] = useful
        if note:
            flags["note"] = note[:500]
        build.flags = flags
        await db.commit()
    return {"flagged": build_id, "useful": useful}


@mcp_server.tool()
async def sia_record_bypass(goal: str, source: str, reason: str | None = None) -> dict:
    """Record that you relied on a source OUTSIDE Sia for this goal (e.g. a
    Google Doc, the web, another connector). This is not a failure to hide — it
    is the signal the operator uses to find and close coverage gaps so Sia
    becomes the better starting point next time. Pass the goal, the source you
    used (a name or URL), and optionally why Sia did not cover it."""
    from app.database import async_session
    from app.models.tables import ContextBypasses

    principal = _principal()
    async with async_session() as db:
        row = ContextBypasses(
            principal_id=principal.id,
            goal=goal[:2000],
            source=source[:500],
            reason=(reason or "")[:1000] or None,
        )
        db.add(row)
        await db.commit()
        return {"recorded": str(row.id), "source": row.source}


@mcp_server.tool()
async def sia_consolidate(clock: str) -> dict:
    """Trigger a consolidation clock (light|rem|deep). Owner only."""
    if not _principal().is_owner:
        raise PermissionError("Owner only")
    from app.jobs.tasks import deep_clock_task, light_clock_task, rem_clock_task

    tasks = {"light": light_clock_task, "rem": rem_clock_task, "deep": deep_clock_task}
    if clock not in tasks:
        raise ValueError(f"Unknown clock: {clock}")
    job_id = await tasks[clock].defer_async()
    return {"status": "queued", "clock": clock, "job_id": job_id}


@mcp_server.tool()
async def sia_resolve_source(source_id: str) -> dict:
    """Resolve a [source:<uuid>] citation to its underlying data-layer record.
    Requires private-visibility trust — the data layer is owner-private and
    includes quarantined/untrusted rows."""
    from app.database import async_session
    from app.models.tables import SourceContent

    if not _principal().can_read_raw_data:
        raise PermissionError("Resolving raw sources requires private visibility")
    async with async_session() as db:
        row = await db.get(SourceContent, uuid.UUID(source_id))
        if row is None:
            raise ValueError("Unknown source")
        return {
            "id": str(row.id),
            "title": row.title,
            "url": row.url,
            "summary": row.summary,
            "trust_tier": row.trust_tier,
            "created_at": str(row.created_at),
        }


async def _read_store_file(path: str, allowed_prefixes: tuple[str, ...]) -> str:
    from app.context.store.documents import MarkdownSerializer
    from app.runtime import get_runtime

    principal = _principal()
    if ".." in path or not path.startswith(allowed_prefixes):
        raise ValueError("Path outside the context store")
    runtime = await get_runtime()
    content = await runtime.context_store.read(path)
    if content is None:
        raise ValueError(f"No such file: {path}")
    document = MarkdownSerializer().loads(path, content)
    visibility = str(document.front.get("visibility", "private"))
    if visibility not in principal.allowed_visibilities:
        raise PermissionError("Not visible to this principal")
    return content


class MCPAuthMiddleware:
    """ASGI wrapper for the /mcp mount: Bearer sia_* key -> principal contextvar."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        authorization = headers.get("authorization", "")
        api_key = authorization.removeprefix("Bearer ").strip()

        from app.database import async_session

        async with async_session() as db:
            principal = await PrincipalService(db).authenticate(api_key)
            await db.commit()
        if principal is None:
            response = JSONResponse(
                {"error": "unauthorized", "detail": "Provide Authorization: Bearer sia_<key>"},
                status_code=401,
            )
            await response(scope, receive, send)
            return

        token = current_principal.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            current_principal.reset(token)


def build_mcp_asgi_app() -> ASGIApp:
    return MCPAuthMiddleware(mcp_server.streamable_http_app())
