import uuid
from datetime import datetime

from pydantic import BaseModel, HttpUrl

from app.models.enums import (
    ArtifactType,
    Pillar,
    ThoughtType,
)


# --- Ingestion ---


class IngestURLRequest(BaseModel):
    url: HttpUrl
    notes: str | None = None
    pillar_override: list[Pillar] | None = None


class IngestThoughtRequest(BaseModel):
    content: str
    pillar: list[Pillar] | None = None
    thought_type: ThoughtType = ThoughtType.IDEA
    related_source_ids: list[uuid.UUID] | None = None


class IngestArtifactRequest(BaseModel):
    title: str
    content: str
    artifact_type: ArtifactType = ArtifactType.FRAMEWORK
    domain: str | None = None
    pillar: list[Pillar] = []


# --- Knowledge ---


class SearchResult(BaseModel):
    id: uuid.UUID
    entity_type: str
    title: str | None = None
    summary: str | None = None
    content_preview: str | None = None
    pillar: list[str] = []
    score: float = 0.0
    created_at: datetime | None = None


class SearchResponse(BaseModel):
    results: list[SearchResult]
    total: int
    query: str


# --- Source Content ---


class SourceContentResponse(BaseModel):
    id: uuid.UUID
    title: str
    url: str | None = None
    summary: str | None = None
    pillar: list[str] = []
    source_type: str
    author: str | None = None
    your_notes: str | None = None
    tags: list[str] = []
    is_consolidated: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Thoughts ---


class ThoughtResponse(BaseModel):
    id: uuid.UUID
    content: str
    pillar: list[str] = []
    thought_type: str
    maturity: str
    related_source_ids: list[uuid.UUID] = []
    is_consolidated: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Artifacts ---


class ArtifactResponse(BaseModel):
    id: uuid.UUID
    title: str
    content: str
    artifact_type: str
    domain: str | None = None
    pillar: list[str] = []
    is_consolidated: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Versions ---


class VersionResponse(BaseModel):
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    version_number: int
    content_snapshot: dict
    diff_from_previous: dict | None = None
    change_reason: str | None = None
    change_type: str
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Config ---


class ConfigResponse(BaseModel):
    config_key: str
    config_value: dict
    description: str | None = None
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConfigUpdateRequest(BaseModel):
    config_value: dict


# --- Auth ---


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- Process Lineage ---


class LineageResponse(BaseModel):
    id: uuid.UUID
    operation_type: str
    prompt_name: str | None = None
    model: str | None = None
    output_entity_type: str | None = None
    output_summary: str | None = None
    quality_score: float | None = None
    duration_ms: int | None = None
    token_count_input: int | None = None
    token_count_output: int | None = None
    cost_usd: float | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Generic ---


class MessageResponse(BaseModel):
    message: str
    id: uuid.UUID | None = None
