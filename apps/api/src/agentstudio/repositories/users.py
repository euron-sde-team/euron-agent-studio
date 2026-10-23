from __future__ import annotations

import uuid

from sqlalchemy import func, select

from agentstudio.models import User
from agentstudio.repositories.base import Repository


class UserRepository(Repository):
    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email.strip()))
        return result.scalar_one_or_none()

    async def user_count(self) -> int:
        return int(await self.session.scalar(select(func.count()).select_from(User)) or 0)

    async def add(self, user: User) -> User:
        self.session.add(user)
        await self.session.flush()
        return user

    async def names(self, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not user_ids:
            return {}
        result = await self.session.execute(select(User.id, User.name).where(User.id.in_(user_ids)))
        return dict(result.tuples().all())
