import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import ContentVersions


def _jsonable(value):
    """Snapshots come straight from ORM rows; coerce non-JSON types defensively."""
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


class VersioningService:
    """Git-like version control for knowledge base items."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_version(
        self,
        entity_type: str,
        entity_id: uuid.UUID,
        content_snapshot: dict,
        change_type: str = "create",
        change_reason: str | None = None,
    ) -> ContentVersions:
        content_snapshot = _jsonable(content_snapshot)
        # Get next version number
        result = await self.db.execute(
            select(func.max(ContentVersions.version_number)).where(
                ContentVersions.entity_type == entity_type,
                ContentVersions.entity_id == entity_id,
            )
        )
        max_version = result.scalar_one_or_none() or 0
        next_version = max_version + 1

        # Compute diff from previous if update
        diff = None
        if next_version > 1:
            prev = await self.db.execute(
                select(ContentVersions).where(
                    ContentVersions.entity_type == entity_type,
                    ContentVersions.entity_id == entity_id,
                    ContentVersions.version_number == max_version,
                )
            )
            prev_row = prev.scalar_one_or_none()
            if prev_row:
                diff = self._compute_diff(prev_row.content_snapshot, content_snapshot)

        version = ContentVersions(
            entity_type=entity_type,
            entity_id=entity_id,
            version_number=next_version,
            content_snapshot=content_snapshot,
            diff_from_previous=diff,
            change_type=change_type,
            change_reason=change_reason,
        )
        self.db.add(version)
        await self.db.flush()
        return version

    async def get_history(
        self, entity_type: str, entity_id: uuid.UUID
    ) -> list[ContentVersions]:
        result = await self.db.execute(
            select(ContentVersions)
            .where(
                ContentVersions.entity_type == entity_type,
                ContentVersions.entity_id == entity_id,
            )
            .order_by(ContentVersions.version_number.desc())
        )
        return list(result.scalars().all())

    async def get_version(
        self, entity_type: str, entity_id: uuid.UUID, version_number: int
    ) -> ContentVersions | None:
        result = await self.db.execute(
            select(ContentVersions).where(
                ContentVersions.entity_type == entity_type,
                ContentVersions.entity_id == entity_id,
                ContentVersions.version_number == version_number,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _compute_diff(old: dict, new: dict) -> dict:
        """Simple JSON diff — tracks added, removed, and changed keys."""
        diff = {"added": {}, "removed": {}, "changed": {}}
        all_keys = set(old.keys()) | set(new.keys())
        for key in all_keys:
            if key not in old:
                diff["added"][key] = new[key]
            elif key not in new:
                diff["removed"][key] = old[key]
            elif old[key] != new[key]:
                diff["changed"][key] = {"from": old[key], "to": new[key]}
        return diff
