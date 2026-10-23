from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select, update

from agentstudio.models import Secret
from agentstudio.repositories.base import Repository


class SecretRepository(Repository):
    async def page(
        self, workspace_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[Secret], int]:
        query = select(Secret).where(Secret.workspace_id == workspace_id)
        total = await self.count(query)
        result = await self.session.execute(query.order_by(Secret.name).limit(limit).offset(offset))
        return list(result.scalars()), total

    async def get(self, workspace_id: uuid.UUID, name: str) -> Secret | None:
        result = await self.session.execute(
            select(Secret).where(Secret.workspace_id == workspace_id, Secret.name == name)
        )
        return result.scalar_one_or_none()

    async def names(self, workspace_id: uuid.UUID) -> frozenset[str]:
        result = await self.session.execute(
            select(Secret.name).where(Secret.workspace_id == workspace_id)
        )
        return frozenset(result.scalars())

    async def by_names(self, workspace_id: uuid.UUID, names: Iterable[str]) -> list[Secret]:
        wanted = sorted(set(names))
        if not wanted:
            return []
        result = await self.session.execute(
            select(Secret).where(Secret.workspace_id == workspace_id, Secret.name.in_(wanted))
        )
        return list(result.scalars())

    async def add(self, secret: Secret) -> Secret:
        self.session.add(secret)
        await self.session.flush()
        return secret

    async def touch(self, secret_ids: list[uuid.UUID], now: datetime) -> None:
        if secret_ids:
            await self.session.execute(
                update(Secret).where(Secret.id.in_(secret_ids)).values(last_used_at=now)
            )
