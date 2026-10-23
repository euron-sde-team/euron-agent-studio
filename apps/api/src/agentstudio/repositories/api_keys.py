from __future__ import annotations

import uuid

from sqlalchemy import select

from agentstudio.models import ApiKey
from agentstudio.repositories.base import Repository


class ApiKeyRepository(Repository):
    async def by_prefix(self, prefix: str) -> ApiKey | None:
        result = await self.session.execute(select(ApiKey).where(ApiKey.prefix == prefix))
        return result.scalar_one_or_none()

    async def get(self, workspace_id: uuid.UUID, key_id: uuid.UUID) -> ApiKey | None:
        result = await self.session.execute(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.workspace_id == workspace_id)
        )
        return result.scalar_one_or_none()

    async def page(
        self, workspace_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[ApiKey], int]:
        query = select(ApiKey).where(ApiKey.workspace_id == workspace_id)
        total = await self.count(query)
        result = await self.session.execute(
            query.order_by(ApiKey.created_at.desc(), ApiKey.id.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars()), total

    async def add(self, key: ApiKey) -> ApiKey:
        self.session.add(key)
        await self.session.flush()
        return key
