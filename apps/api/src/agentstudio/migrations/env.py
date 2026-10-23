"""Alembic environment.

Two entry points share it: the `alembic` CLI (opens its own async engine from
DATABASE_URL) and `agentstudio.db.migrate`, which passes in a connection that already holds
the migration advisory lock.
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy.engine import Connection

import agentstudio.models  # noqa: F401  (registers every table on the metadata)
from agentstudio.core.config import get_settings
from agentstudio.db.base import Base
from agentstudio.db.session import create_engine

config = context.config
target_metadata = Base.metadata


def _configure(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _run_with_new_engine() -> None:
    engine = create_engine(get_settings(), pooled=False, application_name="agentstudio-alembic")
    async with engine.begin() as connection:
        await connection.run_sync(_configure)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
elif (shared := config.attributes.get("connection")) is not None:
    _configure(shared)
else:
    asyncio.run(_run_with_new_engine())
