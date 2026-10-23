"""Knowledge bases: originals on S3 (Floci), chunks and full-text search in Postgres."""

from typing import Any

import httpx
from fastapi import FastAPI

from tests.integration.conftest import Actor, Infra, add_member, aws, base, new_workspace

HANDBOOK = b"""# Travel policy

## Booking
Book flights through the travel portal at least 14 days before departure.
Economy class is the default for flights under six hours.

## Meals
The daily meal allowance is 60 EUR in Europe and 75 USD in North America.
Keep receipts for every meal you claim.
"""

FAQ = b"""Expense claims are submitted in the finance portal within 30 days.
Claims older than 90 days are not reimbursed.
"""


async def new_kb(client: httpx.AsyncClient, actor: Actor, workspace: dict[str, Any]) -> str:
    response = await client.post(
        f"{base(workspace)}/knowledge-bases",
        json={"name": "Finance", "description": "Policies"},
        headers=actor.headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def upload(
    client: httpx.AsyncClient, actor: Actor, workspace: dict[str, Any], kb: str, *files: Any
) -> httpx.Response:
    return await client.post(
        f"{base(workspace)}/knowledge-bases/{kb}/documents",
        files=[("files", item) for item in files],
        headers=actor.headers,
    )


def objects(infra: Infra, workspace: dict[str, Any]) -> list[str]:
    listing = aws("s3").list_objects_v2(
        Bucket=infra.bucket, Prefix=f"workspaces/{workspace['id']}/knowledge/"
    )
    return [item["Key"] for item in listing.get("Contents", [])]


async def test_uploads_are_stored_chunked_and_deduplicated(
    client: httpx.AsyncClient, admin: Actor, infra: Infra
) -> None:
    workspace = await new_workspace(client, admin)
    kb = await new_kb(client, admin, workspace)
    response = await upload(
        client,
        admin,
        workspace,
        kb,
        ("travel.md", HANDBOOK, "text/markdown"),
        ("faq.txt", FAQ, "text/plain"),
    )
    assert response.status_code == 201, response.text
    travel, faq = response.json()
    assert travel["title"] == "Travel policy"
    assert travel["content_type"] == "text/markdown"
    assert travel["chunk_count"] >= 2
    assert faq["title"] == "faq"
    assert len(objects(infra, workspace)) == 2
    again = await upload(
        client, admin, workspace, kb, ("copy-of-travel.md", HANDBOOK, "text/markdown")
    )
    assert again.json()[0]["id"] == travel["id"]
    detail = (
        await client.get(f"{base(workspace)}/knowledge-bases/{kb}", headers=admin.headers)
    ).json()
    assert detail["document_count"] == 2
    assert detail["chunk_count"] == travel["chunk_count"] + faq["chunk_count"]
    original = await client.get(
        f"{base(workspace)}/knowledge-bases/{kb}/documents/{travel['id']}/content",
        headers=admin.headers,
    )
    assert original.content == HANDBOOK
    assert original.headers["content-disposition"] == 'attachment; filename="travel.md"'


async def test_unusable_files_are_refused(
    app: FastAPI, client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    kb = await new_kb(client, admin, workspace)
    pdf = await upload(client, admin, workspace, kb, ("report.pdf", b"%PDF-1.7", "application/pdf"))
    assert pdf.status_code == 415
    binary = await upload(
        client, admin, workspace, kb, ("notes.txt", b"\x00\x01\x02binary", "text/plain")
    )
    assert binary.status_code == 415
    empty = await upload(client, admin, workspace, kb, ("empty.md", b"  \n", "text/markdown"))
    assert empty.status_code == 422
    container = app.state.container
    original = container.settings
    container.settings = original.model_copy(update={"max_document_kb": 1})
    try:
        large = await upload(
            client, admin, workspace, kb, ("big.md", HANDBOOK * 4, "text/markdown")
        )
    finally:
        container.settings = original
    assert large.status_code == 413
    assert large.json()["error"]["code"] == "payload_too_large"


async def test_search_ranks_highlights_and_cites(client: httpx.AsyncClient, admin: Actor) -> None:
    workspace = await new_workspace(client, admin)
    kb = await new_kb(client, admin, workspace)
    await upload(
        client,
        admin,
        workspace,
        kb,
        ("travel.md", HANDBOOK, "text/markdown"),
        ("faq.txt", FAQ, "text/plain"),
    )
    found = await client.post(
        f"{base(workspace)}/knowledge-bases/{kb}/search",
        json={"query": "What is the meal allowance in Europe?", "top_k": 2},
        headers=admin.headers,
    )
    assert found.status_code == 200
    body = found.json()
    top = body["results"][0]
    assert top["heading"] == "Meals"
    assert "60 EUR" in top["text"]
    assert "**" in top["snippet"]
    assert body["context"].startswith("[1] Travel policy")
    nothing = await client.post(
        f"{base(workspace)}/knowledge-bases/{kb}/search",
        json={"query": "quantum chromodynamics"},
        headers=admin.headers,
    )
    assert nothing.json()["results"] == []


async def test_viewers_search_but_only_editors_change_documents(
    client: httpx.AsyncClient, admin: Actor, infra: Infra
) -> None:
    workspace = await new_workspace(client, admin)
    kb = await new_kb(client, admin, workspace)
    document = (await upload(client, admin, workspace, kb, ("faq.txt", FAQ, "text/plain"))).json()[
        0
    ]
    viewer = await add_member(client, admin, workspace, "viewer")
    searched = await client.post(
        f"{base(workspace)}/knowledge-bases/{kb}/search",
        json={"query": "expense claims"},
        headers=viewer.headers,
    )
    assert searched.status_code == 200
    assert len(searched.json()["results"]) == 1
    refused = await upload(client, viewer, workspace, kb, ("x.md", b"# x\nhello", "text/markdown"))
    assert refused.status_code == 403
    removed = await client.delete(
        f"{base(workspace)}/knowledge-bases/{kb}/documents/{document['id']}", headers=admin.headers
    )
    assert removed.status_code == 204
    assert objects(infra, workspace) == []
    gone = await client.post(
        f"{base(workspace)}/knowledge-bases/{kb}/search",
        json={"query": "expense claims"},
        headers=admin.headers,
    )
    assert gone.json()["results"] == []
    assert (
        await client.delete(f"{base(workspace)}/knowledge-bases/{kb}", headers=admin.headers)
    ).status_code == 204
    assert (
        await client.get(f"{base(workspace)}/knowledge-bases/{kb}", headers=admin.headers)
    ).status_code == 404


async def test_knowledge_base_names_are_unique(client: httpx.AsyncClient, admin: Actor) -> None:
    workspace = await new_workspace(client, admin)
    await new_kb(client, admin, workspace)
    duplicate = await client.post(
        f"{base(workspace)}/knowledge-bases", json={"name": "Finance"}, headers=admin.headers
    )
    assert duplicate.status_code == 409
