"""Workspace secrets: write-only credentials for flows, encrypted at rest."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from agentstudio.core.crypto import DecryptionError, secret_context
from agentstudio.core.errors import ConflictError, NotFoundError
from agentstudio.core.logging import get_logger
from agentstudio.models import Secret, Workspace
from agentstudio.repositories.secrets import SecretRepository
from agentstudio.services import audit
from agentstudio.services.container import Container
from agentstudio.services.principal import Principal

log = get_logger("agentstudio.secrets")


class SecretService:
    def __init__(self, container: Container, session: AsyncSession) -> None:
        self.c = container
        self.session = session
        self.secrets = SecretRepository(session)

    async def page(
        self, workspace_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[Secret], int]:
        return await self.secrets.page(workspace_id, limit=limit, offset=offset)

    async def names(self, workspace_id: uuid.UUID) -> frozenset[str]:
        return await self.secrets.names(workspace_id)

    async def create(
        self, workspace: Workspace, principal: Principal, name: str, value: str, description: str
    ) -> Secret:
        if await self.secrets.get(workspace.id, name):
            raise ConflictError(f"A secret named {name} already exists.")
        secret = await self.secrets.add(
            Secret(
                workspace_id=workspace.id,
                name=name,
                description=description.strip(),
                ciphertext=self.c.cipher.encrypt(value, context=secret_context(workspace.id, name)),
                created_by=principal.user_id,
                updated_by=principal.user_id,
            )
        )
        await audit.record(
            self.session,
            workspace_id=workspace.id,
            principal=principal,
            action="secret.created",
            target_type="secret",
            target_id=secret.id,
            details={"name": name},
        )
        await self.session.commit()
        return secret

    async def update(
        self,
        workspace: Workspace,
        principal: Principal,
        name: str,
        *,
        value: str | None,
        description: str | None,
    ) -> Secret:
        secret = await self.secrets.get(workspace.id, name)
        if secret is None:
            raise NotFoundError("Secret not found.")
        if value is not None:
            secret.ciphertext = self.c.cipher.encrypt(
                value, context=secret_context(workspace.id, name)
            )
        if description is not None:
            secret.description = description.strip()
        secret.updated_by = principal.user_id
        secret.updated_at = datetime.now(UTC)
        await audit.record(
            self.session,
            workspace_id=workspace.id,
            principal=principal,
            action="secret.updated",
            target_type="secret",
            target_id=secret.id,
            details={"name": name, "value_changed": value is not None},
        )
        await self.session.commit()
        return secret

    async def delete(self, workspace: Workspace, principal: Principal, name: str) -> None:
        secret = await self.secrets.get(workspace.id, name)
        if secret is None:
            raise NotFoundError("Secret not found.")
        await self.session.delete(secret)
        await audit.record(
            self.session,
            workspace_id=workspace.id,
            principal=principal,
            action="secret.deleted",
            target_type="secret",
            target_id=secret.id,
            details={"name": name},
        )
        await self.session.commit()

    async def resolve(self, workspace_id: uuid.UUID, names: Iterable[str]) -> dict[str, str]:
        """Plaintext values for a run. Missing or undecryptable secrets are simply absent."""
        found = await self.secrets.by_names(workspace_id, names)
        values: dict[str, str] = {}
        for secret in found:
            try:
                values[secret.name] = self.c.cipher.decrypt(
                    secret.ciphertext, context=secret_context(workspace_id, secret.name)
                )
            except DecryptionError:
                log.error("secret_undecryptable", name=secret.name, workspace_id=str(workspace_id))
        await self.secrets.touch([s.id for s in found if s.name in values], datetime.now(UTC))
        return values
