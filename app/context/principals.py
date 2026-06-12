"""Principal registry: who consumes context, with what visibility and budget.

API keys are random secrets shown once at creation; only their sha256 lands in the
database. Lookup is by hash; comparison is therefore constant-time by construction.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Principals

API_KEY_PREFIX = "sia_"


@dataclass(frozen=True)
class Principal:
    id: str
    kind: str
    token_budget: int
    allowed_visibilities: tuple[str, ...]
    allow_fallback: bool

    @property
    def is_owner(self) -> bool:
        return self.kind == "owner"


VISITOR = Principal(
    id="visitor",
    kind="visitor",
    token_budget=2500,
    allowed_visibilities=("public",),
    allow_fallback=False,
)


def _to_principal(row: Principals) -> Principal:
    return Principal(
        id=row.id,
        kind=row.kind,
        token_budget=row.token_budget,
        allowed_visibilities=tuple(row.allowed_visibilities or ["public"]),
        allow_fallback=row.allow_fallback,
    )


def hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


class PrincipalService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def authenticate(self, api_key: str) -> Principal | None:
        if not api_key or not api_key.startswith(API_KEY_PREFIX):
            return None
        row = (
            await self.db.execute(
                select(Principals).where(
                    Principals.api_key_hash == hash_key(api_key),
                    Principals.enabled.is_(True),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        row.last_used_at = datetime.now(timezone.utc)
        await self.db.flush()
        return _to_principal(row)

    async def get(self, principal_id: str) -> Principal | None:
        row = await self.db.get(Principals, principal_id)
        if row is None or not row.enabled:
            return None
        return _to_principal(row)

    async def visitor(self) -> Principal:
        return (await self.get("visitor")) or VISITOR

    async def list_all(self) -> list[dict]:
        rows = (await self.db.execute(select(Principals).order_by(Principals.id))).scalars().all()
        return [
            {
                "id": r.id,
                "display_name": r.display_name,
                "kind": r.kind,
                "token_budget": r.token_budget,
                "allowed_visibilities": r.allowed_visibilities,
                "allow_fallback": r.allow_fallback,
                "has_key": bool(r.api_key_hash),
                "enabled": r.enabled,
                "last_used_at": r.last_used_at,
            }
            for r in rows
        ]

    async def create_agent(
        self,
        purpose: str,
        token_budget: int = 8000,
        allowed_visibilities: list[str] | None = None,
        allow_fallback: bool = False,
    ) -> tuple[str, str]:
        """Create a per-purpose agent principal. Returns (principal_id, api_key) —
        the only time the key is visible."""
        principal_id = f"agent-{purpose}"
        if await self.db.get(Principals, principal_id):
            raise ValueError(f"Principal {principal_id!r} already exists")
        api_key = f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
        self.db.add(
            Principals(
                id=principal_id,
                display_name=f"Agent: {purpose}",
                kind="agent",
                token_budget=token_budget,
                allowed_visibilities=allowed_visibilities or ["public"],
                allow_fallback=allow_fallback,
                api_key_hash=hash_key(api_key),
            )
        )
        await self.db.flush()
        return principal_id, api_key

    async def rotate_key(self, principal_id: str) -> str:
        row = await self.db.get(Principals, principal_id)
        if row is None or row.kind == "visitor":
            raise ValueError(f"Cannot rotate key for {principal_id!r}")
        api_key = f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
        row.api_key_hash = hash_key(api_key)
        await self.db.flush()
        return api_key

    async def revoke(self, principal_id: str) -> None:
        row = await self.db.get(Principals, principal_id)
        if row is None or row.kind == "owner":
            raise ValueError(f"Cannot revoke {principal_id!r}")
        row.enabled = False
        row.api_key_hash = None
        await self.db.flush()


def new_owner_key() -> tuple[str, str]:
    """Generate an owner API key + hash (used by setup tooling)."""
    api_key = f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    return api_key, hash_key(api_key)
