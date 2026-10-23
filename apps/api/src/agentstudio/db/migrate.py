"""Apply pending migrations from inside the application.

Runs under a transaction-scoped advisory lock, so any number of API replicas can boot at
the same time and the migrations still run exactly once.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection

import agentstudio
from agentstudio.core.config import Settings
from agentstudio.db.session import create_engine

# Arbitrary, stable 64-bit key: "agstudio" in ASCII.
MIGRATION_LOCK_KEY = 0x616773747564696F


def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(agentstudio.__file__).parent / "migrations"))
    return config


def _upgrade(connection: Connection, revision: str) -> None:
    config = alembic_config()
    config.attributes["connection"] = connection
    command.upgrade(config, revision)


async def migrate(settings: Settings, revision: str = "head") -> None:
    engine = create_engine(settings, pooled=False, application_name="agentstudio-migrate")
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK_KEY}
            )
            await conn.run_sync(_upgrade, revision)
    finally:
        await engine.dispose()
