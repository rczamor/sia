"""ContextBuilder-grounded dialogue API."""

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.principals import PrincipalService
from app.data.lineage import LineageService, TrackedLLMProvider
from app.database import get_db
from app.prompts.dialogue import DIALOGUE_PARTNER
from app.runtime import get_runtime

router = APIRouter(prefix="/api", tags=["chatbot"])


class ChatRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    budget_tokens: int | None = Field(default=None, ge=500, le=50000)
    pillar: str | None = None


class ChatResponse(BaseModel):
    answer: str
    build_id: str
    principal: str
    coverage: float
    tokens_used: int
    sources: list[dict]
    fallback_unconsolidated: list[dict]
    cautions: list[str]


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """Answer a question using a freshly built context artifact.

    Anonymous callers receive the visitor principal. Authenticated owners and
    agents receive the same answer path but with their registered visibility,
    budget, and fallback settings.
    """
    principal = getattr(request.state, "principal", None)
    if principal is None:
        principal = await PrincipalService(db).visitor()

    runtime = await get_runtime()
    try:
        artifact = await runtime.build_context(
            db,
            goal=body.question,
            principal=principal,
            budget_tokens=body.budget_tokens,
            pillar_hint=body.pillar,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503, detail=f"Embeddings provider unavailable: {exc}"
        )

    try:
        provider, params = runtime.llm_for("dialogue")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    llm = TrackedLLMProvider(provider, LineageService(db), llmops=runtime.llmops)
    prompt_template = await llm.prompt("dialogue_partner", DIALOGUE_PARTNER)
    try:
        prompt = prompt_template.format(
            context=artifact.to_markdown(),
            question=body.question,
        )
    except (KeyError, IndexError, ValueError):
        prompt = DIALOGUE_PARTNER.format(
            context=artifact.to_markdown(),
            question=body.question,
        )

    response = await llm.complete(
        messages=[{"role": "user", "content": prompt}],
        model=params.get("model"),
        temperature=params.get("temperature", 0.4),
        max_tokens=params.get("max_tokens", 1200),
        operation_type="dialogue",
        prompt_name="dialogue_partner",
    )
    await db.commit()

    return ChatResponse(
        answer=response.content,
        build_id=str(artifact.build_id),
        principal=artifact.principal_id,
        coverage=round(artifact.coverage, 3),
        tokens_used=artifact.tokens_used,
        sources=[
            {
                "path": section.path,
                "kind": section.kind,
                "title": section.title,
                "reason": section.reason,
                "score": round(section.score, 3),
            }
            for section in artifact.sections[:8]
        ],
        fallback_unconsolidated=artifact.fallback,
        cautions=artifact.cautions,
    )
