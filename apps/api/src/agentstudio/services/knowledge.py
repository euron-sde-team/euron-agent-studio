"""Knowledge bases: upload text and Markdown, chunk it, search it with Postgres full-text."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict
from pathlib import PurePath
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agentstudio.core.errors import (
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    UnprocessableError,
    UnsupportedMediaTypeError,
)
from agentstudio.core.ids import uuid7
from agentstudio.core.logging import get_logger
from agentstudio.engine import runtime
from agentstudio.ingestion.chunker import chunk_document, title_of
from agentstudio.integrations.storage import knowledge_key
from agentstudio.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument, Workspace
from agentstudio.repositories.knowledge import KnowledgeRepository, SearchHit
from agentstudio.services import audit
from agentstudio.services.container import Container
from agentstudio.services.principal import Principal

log = get_logger("agentstudio.knowledge")

CONTENT_TYPES = {".md": "text/markdown", ".markdown": "text/markdown", ".txt": "text/plain"}


class KnowledgeService:
    def __init__(self, container: Container, session: AsyncSession) -> None:
        self.c = container
        self.session = session
        self.repo = KnowledgeRepository(session)

    # Knowledge bases ---------------------------------------------------------------------

    async def page(
        self, workspace_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[KnowledgeBase], int]:
        return await self.repo.page(workspace_id, limit=limit, offset=offset)

    async def get(self, workspace_id: uuid.UUID, kb_id: uuid.UUID) -> KnowledgeBase:
        kb = await self.repo.get(workspace_id, kb_id)
        if kb is None:
            raise NotFoundError("Knowledge base not found.")
        return kb

    async def ids(self, workspace_id: uuid.UUID) -> frozenset[uuid.UUID]:
        return await self.repo.ids(workspace_id)

    async def by_name(self, workspace_id: uuid.UUID, name: str) -> KnowledgeBase | None:
        return await self.repo.by_name(workspace_id, name)

    async def create(
        self, workspace: Workspace, principal: Principal, name: str, description: str = ""
    ) -> KnowledgeBase:
        if await self.repo.by_name(workspace.id, name.strip()):
            raise ConflictError("A knowledge base with that name already exists.")
        kb = await self.repo.add(
            KnowledgeBase(
                workspace_id=workspace.id,
                name=name.strip(),
                description=description.strip(),
                created_by=principal.user_id,
            )
        )
        await audit.record(
            self.session,
            workspace_id=workspace.id,
            principal=principal,
            action="knowledge_base.created",
            target_type="knowledge_base",
            target_id=kb.id,
            details={"name": kb.name},
        )
        await self.session.commit()
        return kb

    async def update(
        self,
        workspace: Workspace,
        principal: Principal,
        kb_id: uuid.UUID,
        *,
        name: str | None,
        description: str | None,
    ) -> KnowledgeBase:
        kb = await self.get(workspace.id, kb_id)
        if name is not None and name.strip() != kb.name:
            if await self.repo.by_name(workspace.id, name.strip()):
                raise ConflictError("A knowledge base with that name already exists.")
            kb.name = name.strip()
        if description is not None:
            kb.description = description.strip()
        await audit.record(
            self.session,
            workspace_id=workspace.id,
            principal=principal,
            action="knowledge_base.updated",
            target_type="knowledge_base",
            target_id=kb.id,
            details={"name": kb.name},
        )
        await self.session.commit()
        return kb

    async def delete(self, workspace: Workspace, principal: Principal, kb_id: uuid.UUID) -> None:
        kb = await self.get(workspace.id, kb_id)
        keys = await self.repo.storage_keys(workspace.id, kb.id)
        await self.session.delete(kb)
        await audit.record(
            self.session,
            workspace_id=workspace.id,
            principal=principal,
            action="knowledge_base.deleted",
            target_type="knowledge_base",
            target_id=kb.id,
            details={"name": kb.name, "documents": len(keys)},
        )
        await self.session.commit()
        await self._delete_files(keys)

    # Documents ---------------------------------------------------------------------------

    async def documents(
        self, workspace_id: uuid.UUID, kb_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[KnowledgeDocument], int]:
        await self.get(workspace_id, kb_id)
        return await self.repo.documents(workspace_id, kb_id, limit=limit, offset=offset)

    async def document(self, workspace_id: uuid.UUID, document_id: uuid.UUID) -> KnowledgeDocument:
        document = await self.repo.document(workspace_id, document_id)
        if document is None:
            raise NotFoundError("Document not found.")
        return document

    async def upload(
        self,
        workspace: Workspace,
        principal: Principal,
        kb_id: uuid.UUID,
        filename: str,
        data: bytes,
    ) -> tuple[KnowledgeDocument, bool]:
        """Store, chunk and index one file. Returns the document and whether it is new."""
        kb = await self.get(workspace.id, kb_id)
        name = PurePath(filename or "document.txt").name[:300] or "document.txt"
        extension = PurePath(name).suffix.lower()
        content_type = CONTENT_TYPES.get(extension)
        if content_type is None:
            raise UnsupportedMediaTypeError("Upload .md, .markdown or .txt files.")
        if len(data) > self.c.settings.max_document_bytes:
            raise PayloadTooLargeError(
                f"Documents are limited to {self.c.settings.max_document_kb} KB."
            )
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise UnsupportedMediaTypeError("The file is not UTF-8 text.") from exc
        if "\x00" in text:
            raise UnsupportedMediaTypeError("The file looks binary, not text.")
        if not text.strip():
            raise UnprocessableError("The file is empty.")
        digest = hashlib.sha256(data).hexdigest()
        existing = await self.repo.document_by_hash(kb.id, digest)
        if existing is not None:
            return existing, False

        title = title_of(text, PurePath(name).stem.replace("-", " ").replace("_", " ").strip())
        chunks = chunk_document(text, title=title)
        document_id = uuid7()
        key = knowledge_key(
            workspace.id, kb.id, document_id, extension if extension != ".markdown" else ".md"
        )
        await self.c.storage.put(key, data, content_type)
        document = KnowledgeDocument(
            id=document_id,
            knowledge_base_id=kb.id,
            workspace_id=workspace.id,
            title=title,
            filename=name,
            content_type=content_type,
            size_bytes=len(data),
            sha256=digest,
            storage_key=key,
            chunk_count=len(chunks),
            token_count=sum(chunk.token_count for chunk in chunks),
            created_by=principal.user_id,
        )
        rows = [
            KnowledgeChunk(
                document_id=document_id,
                knowledge_base_id=kb.id,
                workspace_id=workspace.id,
                ordinal=chunk.ordinal,
                heading=chunk.heading,
                text=chunk.text,
                token_count=chunk.token_count,
            )
            for chunk in chunks
        ]
        try:
            await self.repo.add_document(document, rows)
            await self.repo.refresh_counts(kb.id)
            await audit.record(
                self.session,
                workspace_id=workspace.id,
                principal=principal,
                action="knowledge_document.uploaded",
                target_type="knowledge_document",
                target_id=document.id,
                details={"title": title, "knowledge_base": kb.name, "chunks": len(chunks)},
            )
            await self.session.commit()
        except IntegrityError:
            # The same file uploaded twice at once: the other upload won.
            await self.session.rollback()
            await self._delete_files([key])
            winner = await self.repo.document_by_hash(kb.id, digest)
            if winner is None:
                raise
            return winner, False
        return document, True

    async def delete_document(
        self, workspace: Workspace, principal: Principal, document_id: uuid.UUID
    ) -> None:
        document = await self.document(workspace.id, document_id)
        key = document.storage_key
        kb_id = document.knowledge_base_id
        await self.session.delete(document)
        await self.session.flush()
        await self.repo.refresh_counts(kb_id)
        await audit.record(
            self.session,
            workspace_id=workspace.id,
            principal=principal,
            action="knowledge_document.deleted",
            target_type="knowledge_document",
            target_id=document_id,
            details={"title": document.title},
        )
        await self.session.commit()
        await self._delete_files([key])

    async def content(
        self, workspace_id: uuid.UUID, document_id: uuid.UUID
    ) -> tuple[KnowledgeDocument, bytes]:
        document = await self.document(workspace_id, document_id)
        return document, await self.c.storage.get(document.storage_key)

    async def search_with_context(
        self, workspace_id: uuid.UUID, kb_id: uuid.UUID, query: str, top_k: int
    ) -> tuple[list[SearchHit], str]:
        """Hits and the numbered context a Knowledge search node would hand a prompt."""
        await self.get(workspace_id, kb_id)
        hits = await self.repo.search(workspace_id, kb_id, query, top_k)
        return hits, runtime.knowledge_context([hit_dict(hit) for hit in hits])

    async def _delete_files(self, keys: list[str]) -> None:
        for key in keys:
            try:
                await self.c.storage.delete(key)
            except Exception:
                log.warning("storage_delete_failed", key=key)


def hit_dict(hit: SearchHit) -> dict[str, Any]:
    data = asdict(hit)
    data["chunk_id"] = str(hit.chunk_id)
    data["document_id"] = str(hit.document_id)
    return data


class WorkspaceKnowledge:
    """The engine's `KnowledgeSearcher` port, bound to one workspace."""

    def __init__(self, container: Container, workspace_id: uuid.UUID) -> None:
        self.c = container
        self.workspace_id = workspace_id

    async def search(
        self, knowledge_base_id: uuid.UUID, query: str, top_k: int
    ) -> list[dict[str, Any]]:
        async with self.c.db.session() as session:
            hits = await KnowledgeRepository(session).search(
                self.workspace_id, knowledge_base_id, query, top_k
            )
        return [hit_dict(hit) for hit in hits]
