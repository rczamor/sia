from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.schemas import ConfigUpdateRequest
from app.models.tables import AiConfig

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/")
async def list_config(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AiConfig).order_by(AiConfig.config_key))
    configs = result.scalars().all()
    return [
        {
            "config_key": c.config_key,
            "config_value": c.config_value,
            "description": c.description,
            "updated_at": c.updated_at,
        }
        for c in configs
    ]


@router.put("/{key}")
async def update_config(
    key: str, request: ConfigUpdateRequest, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        update(AiConfig)
        .where(AiConfig.config_key == key)
        .values(config_value=request.config_value)
        .returning(AiConfig)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")
    await db.commit()
    return {"message": "Updated", "config_key": key}
