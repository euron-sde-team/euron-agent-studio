from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, update

from agentstudio.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from agentstudio.repositories.base import Repository

# ts_headline marks matches with ** so the text stays plain (rendered safely by the web app).
_HEADLINE = (
    "MaxWords=45, MinWords=15, ShortWord=3, MaxFragments=2, FragmentDelimiter=' ... ', "
    "StartSel=**, StopSel=**"
)
_TERM = re.compile(r"[a-z0-9]{2,}")


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    title: str
    heading: str
    text: str
    snippet: str
    score: float


class KnowledgeRepository(Repository):
    # Knowledge bases ---------------------------------------------------------------------

    async def get(self, workspace_id: uuid.UUID, kb_id: uuid.UUID) -> KnowledgeBase | None:
        result = await self.session.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id, KnowledgeBase.workspace_id == workspace_id
            )
        )
        return result.scalar_one_or_none()

    async def by_name(self, workspace_id: uuid.UUID, name: str) -> KnowledgeBase | None:
        result = await self.session.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.workspace_id == workspace_id, KnowledgeBase.name == name
            )
        )
        return result.scalar_one_or_none()

    async def ids(self, workspace_id: uuid.UUID) -> frozenset[uuid.UUID]:
        result = await self.session.execute(
            select(KnowledgeBase.id).where(KnowledgeBase.workspace_id == workspace_id)
        )
        return frozenset(result.scalars())

    async def page(
        self, workspace_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[KnowledgeBase], int]:
        query = select(KnowledgeBase).where(KnowledgeBase.workspace_id == workspace_id)
        total = await self.count(query)
        result = await self.session.execute(
            query.order_by(KnowledgeBase.name).limit(limit).offset(offset)
        )
        return list(result.scalars()), total

    async def add(self, kb: KnowledgeBase) -> KnowledgeBase:
        self.session.add(kb)
        await self.session.flush()
        return kb

    async def refresh_counts(self, kb_id: uuid.UUID) -> None:
        documents = (
            select(func.count())
            .where(KnowledgeDocument.knowledge_base_id == kb_id)
            .scalar_subquery()
        )
        chunks = (
            select(func.count()).where(KnowledgeChunk.knowledge_base_id == kb_id).scalar_subquery()
        )
        await self.session.execute(
            update(KnowledgeBase)
            .where(KnowledgeBase.id == kb_id)
            .values(document_count=documents, chunk_count=chunks, updated_at=func.now())
        )

    # Documents ---------------------------------------------------------------------------

    async def document(
        self, workspace_id: uuid.UUID, document_id: uuid.UUID
    ) -> KnowledgeDocument | None:
        result = await self.session.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.id == document_id, KnowledgeDocument.workspace_id == workspace_id
            )
        )
        return result.scalar_one_or_none()

    async def document_by_hash(self, kb_id: uuid.UUID, sha256: str) -> KnowledgeDocument | None:
        result = await self.session.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.knowledge_base_id == kb_id, KnowledgeDocument.sha256 == sha256
            )
        )
        return result.scalar_one_or_none()

    async def documents(
        self, workspace_id: uuid.UUID, kb_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[KnowledgeDocument], int]:
        query = select(KnowledgeDocument).where(
            KnowledgeDocument.workspace_id == workspace_id,
            KnowledgeDocument.knowledge_base_id == kb_id,
        )
        total = await self.count(query)
        result = await self.session.execute(
            query.order_by(KnowledgeDocument.title, KnowledgeDocument.id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars()), total

    async def storage_keys(
        self, workspace_id: uuid.UUID, kb_id: uuid.UUID | None = None
    ) -> list[str]:
        query = select(KnowledgeDocument.storage_key).where(
            KnowledgeDocument.workspace_id == workspace_id
        )
        if kb_id is not None:
            query = query.where(KnowledgeDocument.knowledge_base_id == kb_id)
        return list((await self.session.execute(query)).scalars())

    async def add_document(self, document: KnowledgeDocument, chunks: list[KnowledgeChunk]) -> None:
        self.session.add(document)
        await self.session.flush()
        self.session.add_all(chunks)
        await self.session.flush()

    # Search ------------------------------------------------------------------------------

    async def search(
        self, workspace_id: uuid.UUID, kb_id: uuid.UUID, query: str, top_k: int
    ) -> list[SearchHit]:
        """Full-text search: every term first, then any term when that finds nothing."""
        hits = await self._search(
            workspace_id, kb_id, func.websearch_to_tsquery("english", query), top_k
        )
        if hits:
            return hits
        terms = _TERM.findall(query.lower())
        if not terms:
            return []
        anything = func.to_tsquery("english", " | ".join(dict.fromkeys(terms)))
        return await self._search(workspace_id, kb_id, anything, top_k)

    async def _search(
        self, workspace_id: uuid.UUID, kb_id: uuid.UUID, tsquery: object, top_k: int
    ) -> list[SearchHit]:
        rank = func.ts_rank_cd(KnowledgeChunk.tsv, tsquery, 32).label("rank")
        headline = func.ts_headline("english", KnowledgeChunk.text, tsquery, _HEADLINE)
        result = await self.session.execute(
            select(KnowledgeChunk, KnowledgeDocument.title, rank, headline)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(
                KnowledgeChunk.workspace_id == workspace_id,
                KnowledgeChunk.knowledge_base_id == kb_id,
                KnowledgeChunk.tsv.op("@@")(tsquery),
            )
            .order_by(rank.desc(), KnowledgeChunk.id)
            .limit(top_k)
        )
        return [
            SearchHit(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                title=title,
                heading=chunk.heading,
                text=chunk.text,
                snippet=snippet,
                score=round(float(score), 4),
            )
            for chunk, title, score, snippet in result.all()
        ]
