"""Knowledge bases: text and Markdown documents searched by flows."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import Response

from agentstudio.api.deps import ContainerDep, EditorDep, SessionDep, ViewerDep, rate_limit
from agentstudio.core.errors import PayloadTooLargeError
from agentstudio.schemas.common import Limit, Offset, Page
from agentstudio.schemas.knowledge import (
    DocumentOut,
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
    KnowledgeBaseUpdate,
    SearchHitOut,
    SearchIn,
    SearchOut,
)
from agentstudio.services.knowledge import KnowledgeService

router = APIRouter(prefix="/api/v1/workspaces/{workspace}/knowledge-bases", tags=["knowledge"])


@router.get("", summary="Knowledge bases in this workspace")
async def list_knowledge_bases(
    ctx: ViewerDep,
    container: ContainerDep,
    session: SessionDep,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[KnowledgeBaseOut]:
    kbs, total = await KnowledgeService(container, session).page(ctx.id, limit=limit, offset=offset)
    return Page(
        items=[KnowledgeBaseOut.model_validate(kb) for kb in kbs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", summary="Create a knowledge base", status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    body: KnowledgeBaseCreate, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> KnowledgeBaseOut:
    kb = await KnowledgeService(container, session).create(
        ctx.workspace, ctx.principal, body.name, body.description
    )
    return KnowledgeBaseOut.model_validate(kb)


@router.get("/{kb_id}", summary="One knowledge base")
async def get_knowledge_base(
    kb_id: uuid.UUID, ctx: ViewerDep, container: ContainerDep, session: SessionDep
) -> KnowledgeBaseOut:
    return KnowledgeBaseOut.model_validate(
        await KnowledgeService(container, session).get(ctx.id, kb_id)
    )


@router.patch("/{kb_id}", summary="Rename or describe a knowledge base")
async def update_knowledge_base(
    kb_id: uuid.UUID,
    body: KnowledgeBaseUpdate,
    ctx: EditorDep,
    container: ContainerDep,
    session: SessionDep,
) -> KnowledgeBaseOut:
    kb = await KnowledgeService(container, session).update(
        ctx.workspace, ctx.principal, kb_id, name=body.name, description=body.description
    )
    return KnowledgeBaseOut.model_validate(kb)


@router.delete("/{kb_id}", summary="Delete a knowledge base and its documents", status_code=204)
async def delete_knowledge_base(
    kb_id: uuid.UUID, ctx: EditorDep, container: ContainerDep, session: SessionDep
) -> None:
    await KnowledgeService(container, session).delete(ctx.workspace, ctx.principal, kb_id)


@router.get("/{kb_id}/documents", summary="Documents in a knowledge base")
async def list_documents(
    kb_id: uuid.UUID,
    ctx: ViewerDep,
    container: ContainerDep,
    session: SessionDep,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[DocumentOut]:
    documents, total = await KnowledgeService(container, session).documents(
        ctx.id, kb_id, limit=limit, offset=offset
    )
    return Page(
        items=[DocumentOut.model_validate(d) for d in documents],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{kb_id}/documents",
    summary="Upload .md or .txt files (the same file twice is one document)",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("upload", "rate_limit_upload"))],
)
async def upload_documents(
    kb_id: uuid.UUID,
    files: Annotated[list[UploadFile], File(description="Up to 20 text or Markdown files.")],
    ctx: EditorDep,
    container: ContainerDep,
    session: SessionDep,
) -> list[DocumentOut]:
    if len(files) > 20:
        raise PayloadTooLargeError("Upload at most 20 files at a time.")
    service = KnowledgeService(container, session)
    limit = container.settings.max_document_bytes
    documents = []
    for upload in files:
        data = await upload.read(limit + 1)
        document, _ = await service.upload(
            ctx.workspace, ctx.principal, kb_id, upload.filename or "", data
        )
        documents.append(DocumentOut.model_validate(document))
    return documents


@router.get("/{kb_id}/documents/{document_id}", summary="One document")
async def get_document(
    kb_id: uuid.UUID,
    document_id: uuid.UUID,
    ctx: ViewerDep,
    container: ContainerDep,
    session: SessionDep,
) -> DocumentOut:
    return DocumentOut.model_validate(
        await KnowledgeService(container, session).document(ctx.id, document_id)
    )


@router.get(
    "/{kb_id}/documents/{document_id}/content",
    summary="Download the original file",
    response_class=Response,
)
async def download_document(
    kb_id: uuid.UUID,
    document_id: uuid.UUID,
    ctx: ViewerDep,
    container: ContainerDep,
    session: SessionDep,
) -> Response:
    document, data = await KnowledgeService(container, session).content(ctx.id, document_id)
    return Response(
        data,
        media_type=f"{document.content_type}; charset=utf-8",
        headers={"content-disposition": f'attachment; filename="{document.filename}"'},
    )


@router.delete("/{kb_id}/documents/{document_id}", summary="Delete a document", status_code=204)
async def delete_document(
    kb_id: uuid.UUID,
    document_id: uuid.UUID,
    ctx: EditorDep,
    container: ContainerDep,
    session: SessionDep,
) -> None:
    await KnowledgeService(container, session).delete_document(
        ctx.workspace, ctx.principal, document_id
    )


@router.post("/{kb_id}/search", summary="Full-text search, as a Knowledge search node runs it")
async def search(
    kb_id: uuid.UUID, body: SearchIn, ctx: ViewerDep, container: ContainerDep, session: SessionDep
) -> SearchOut:
    hits, context = await KnowledgeService(container, session).search_with_context(
        ctx.id, kb_id, body.query, body.top_k
    )
    return SearchOut(results=[SearchHitOut.model_validate(hit) for hit in hits], context=context)
