import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.ingestion import IngestionService
from app.data.lineage import LineageService, TrackedLLMProvider
from tests.fakes import FakeEmbedding, FakeLLM


@pytest.fixture
def fake_ingestion(monkeypatch):
    """Route the ingestion API through fake LLM + embedding providers."""
    fake_llm = FakeLLM()

    async def fake_service(db: AsyncSession) -> IngestionService:
        return IngestionService(
            db, TrackedLLMProvider(fake_llm, LineageService(db)), FakeEmbedding()
        )

    monkeypatch.setattr("app.api.ingest._get_ingestion_service", fake_service)
    return fake_llm


async def test_ingest_thought_roundtrip(client, fake_ingestion, db_session):
    response = await client.post(
        "/api/ingest/thought",
        json={"content": "Context must be synthesized, not retrieved.", "pillar": ["context_layers"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["pillar"] == ["context_layers"]

    # Stored with embedding, searchable, and versioned
    from sqlalchemy import text

    row = (await db_session.execute(text("SELECT content, embedding FROM my_thoughts"))).first()
    assert row is not None
    assert row.embedding is not None
    version = (
        await db_session.execute(text("SELECT version_number FROM content_versions"))
    ).scalar()
    assert version == 1


async def test_ingest_thought_autoclassifies_without_pillar(client, fake_ingestion):
    response = await client.post("/api/ingest/thought", json={"content": "A pillar-less thought"})
    assert response.status_code == 200
    assert response.json()["pillar"] == ["context_layers"]  # from FakeLLM's canned response
    assert len(fake_ingestion.calls) == 1  # classification was invoked


async def test_ingest_thought_records_lineage(client, fake_ingestion, db_session):
    await client.post("/api/ingest/thought", json={"content": "Lineage check"})
    from sqlalchemy import text

    op = (await db_session.execute(text("SELECT operation_type FROM process_lineage"))).scalar()
    assert op == "classify"


async def test_search_finds_ingested_artifact(client, fake_ingestion, db_session):
    response = await client.post(
        "/api/ingest/expertise",
        json={
            "title": "RRF fusion notes",
            "content": "Reciprocal rank fusion combines rankings across heterogeneous scorers.",
            "pillar": ["context_layers"],
        },
    )
    assert response.status_code == 200

    # Search goes through the same fake embedder
    from app.retrieval.search import SearchService

    service = SearchService(db_session, FakeEmbedding())
    results = await service.search(query="reciprocal rank fusion")
    assert any(r["entity_type"] == "expertise_artifacts" for r in results)
    assert all(isinstance(r["score"], float) for r in results)
