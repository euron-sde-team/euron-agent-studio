from __future__ import annotations

from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession


class Repository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def count(self, query: Select[*tuple[Any, ...]]) -> int:
        """Rows a filtered query would return, without its ordering or paging."""
        counted = select(func.count()).select_from(
            query.order_by(None).limit(None).offset(None).subquery()
        )
        return int(await self.session.scalar(counted) or 0)
