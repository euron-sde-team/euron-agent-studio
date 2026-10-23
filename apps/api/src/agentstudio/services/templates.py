"""Installing templates into a workspace: the knowledge they search, bound to real ids."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from agentstudio.core.errors import NotFoundError
from agentstudio.models import Workspace
from agentstudio.services.container import Container
from agentstudio.services.knowledge import KnowledgeService
from agentstudio.services.principal import Principal
from agentstudio.templates import (
    TEMPLATES,
    KnowledgeSpec,
    Template,
    bind_knowledge,
    get_template,
    knowledge_documents,
    knowledge_names,
)


class TemplateService:
    def __init__(self, container: Container, session: AsyncSession) -> None:
        self.c = container
        self.session = session
        self.knowledge = KnowledgeService(container, session)

    @staticmethod
    def all() -> tuple[Template, ...]:
        return TEMPLATES

    @staticmethod
    def get(slug: str) -> Template:
        template = get_template(slug)
        if template is None:
            raise NotFoundError("Template not found.")
        return template

    async def ensure_knowledge(
        self, workspace: Workspace, principal: Principal, spec: KnowledgeSpec
    ) -> uuid.UUID:
        """The workspace's knowledge base of that name, created with its documents if missing."""
        kb = await self.knowledge.by_name(workspace.id, spec.name)
        if kb is None:
            kb = await self.knowledge.create(workspace, principal, spec.name, spec.description)
        if kb.document_count == 0:
            for filename, data in knowledge_documents(spec):
                await self.knowledge.upload(workspace, principal, kb.id, filename, data)
        return kb.id

    async def graph(
        self, workspace: Workspace, principal: Principal, template: Template
    ) -> dict[str, Any]:
        ids: dict[str, uuid.UUID] = {}
        for name in knowledge_names(template.graph):
            spec = next(k for k in template.knowledge if k.name == name)
            ids[name] = await self.ensure_knowledge(workspace, principal, spec)
        return bind_knowledge(template.graph, ids)
