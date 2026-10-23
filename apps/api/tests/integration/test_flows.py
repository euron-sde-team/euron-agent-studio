import copy

import httpx

from tests.integration.conftest import Actor, add_member, base, create_flow, new_workspace


async def test_a_blank_flow_is_valid_and_lists_with_stats(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    flow = await create_flow(client, admin, workspace, name="Echo", tags=["Demo", "demo", " Ops "])
    assert flow["issues"] == []
    assert flow["tags"] == ["demo", "ops"]
    assert flow["node_types"] == ["start", "output"]
    assert flow["published_version"] is None
    listing = await client.get(f"{base(workspace)}/flows?q=ech", headers=admin.headers)
    assert listing.json()["total"] == 1
    assert (await client.get(f"{base(workspace)}/flows?tag=ops", headers=admin.headers)).json()[
        "total"
    ] == 1
    assert (
        await client.get(f"{base(workspace)}/flows?published=true", headers=admin.headers)
    ).json()["total"] == 0
    assert (await client.get(f"{base(workspace)}/flows/tags", headers=admin.headers)).json() == [
        "demo",
        "ops",
    ]


async def test_templates_install_with_their_knowledge(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    flow = await create_flow(client, admin, workspace, name="Triage", template="support-triage")
    assert flow["issues"] == []
    assert flow["template_slug"] == "support-triage"
    assert "approval" in flow["node_types"]
    kbs = (await client.get(f"{base(workspace)}/knowledge-bases", headers=admin.headers)).json()[
        "items"
    ]
    assert [(kb["name"], kb["document_count"]) for kb in kbs] == [("Help center", 5)]
    again = await create_flow(client, admin, workspace, name="Triage 2", template="support-triage")
    assert again["issues"] == []
    assert (await client.get(f"{base(workspace)}/knowledge-bases", headers=admin.headers)).json()[
        "total"
    ] == 1
    missing = await client.post(
        f"{base(workspace)}/flows", json={"name": "x", "template": "nope"}, headers=admin.headers
    )
    assert missing.status_code == 404


async def test_drafts_save_with_optimistic_concurrency(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    flow = await create_flow(client, admin, workspace)
    graph = copy.deepcopy(flow["graph"])
    graph["nodes"][1]["config"]["fields"][0]["value"] = "Hello {{inputs.input}}"
    saved = await client.put(
        f"{base(workspace)}/flows/{flow['id']}/draft",
        json={"graph": graph, "base_revision": 1},
        headers=admin.headers,
    )
    assert saved.status_code == 200
    assert saved.json()["draft_revision"] == 2
    stale = await client.put(
        f"{base(workspace)}/flows/{flow['id']}/draft",
        json={"graph": graph, "base_revision": 1},
        headers=admin.headers,
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "revision_conflict"
    assert stale.json()["error"]["details"] == {"current_revision": 2}
    malformed = await client.put(
        f"{base(workspace)}/flows/{flow['id']}/draft",
        json={"graph": {"nodes": [{"id": "Bad Id", "type": "llm"}]}, "base_revision": 2},
        headers=admin.headers,
    )
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "invalid_graph"


async def test_validation_reports_issues_inline(client: httpx.AsyncClient, admin: Actor) -> None:
    workspace = await new_workspace(client, admin)
    flow = await create_flow(client, admin, workspace)
    graph = copy.deepcopy(flow["graph"])
    graph["nodes"].append({"id": "orphan", "type": "llm", "config": {"prompt": "{{ghost.text}}"}})
    graph["nodes"].append(
        {
            "id": "kb",
            "type": "knowledge",
            "config": {"knowledge_base_id": "00000000-0000-7000-8000-000000000001", "query": "x"},
        }
    )
    result = await client.post(
        f"{base(workspace)}/flows/{flow['id']}/validate",
        json={"graph": graph},
        headers=admin.headers,
    )
    assert result.status_code == 200
    body = result.json()
    assert body["valid"] is False
    codes = {(i["code"], i["node_id"]) for i in body["issues"]}
    assert ("missing_input", "orphan") in codes
    assert ("unknown_reference", "orphan") in codes
    assert ("unknown_knowledge_base", "kb") in codes


async def test_publishing_versions_and_restoring(client: httpx.AsyncClient, admin: Actor) -> None:
    workspace = await new_workspace(client, admin)
    flow = await create_flow(client, admin, workspace)
    first = await client.post(
        f"{base(workspace)}/flows/{flow['id']}/publish", json={"notes": "v1"}, headers=admin.headers
    )
    assert first.status_code == 201
    assert first.json()["version"] == 1
    assert first.json()["published"] is True
    graph = copy.deepcopy(flow["graph"])
    graph["nodes"][1]["config"]["fields"][0]["value"] = "Changed"
    await client.put(
        f"{base(workspace)}/flows/{flow['id']}/draft",
        json={"graph": graph, "base_revision": 1},
        headers=admin.headers,
    )
    second = await client.post(
        f"{base(workspace)}/flows/{flow['id']}/publish", json={}, headers=admin.headers
    )
    assert second.json()["version"] == 2
    versions = await client.get(
        f"{base(workspace)}/flows/{flow['id']}/versions", headers=admin.headers
    )
    assert [(v["version"], v["published"]) for v in versions.json()["items"]] == [
        (2, True),
        (1, False),
    ]
    one = await client.get(
        f"{base(workspace)}/flows/{flow['id']}/versions/1", headers=admin.headers
    )
    assert one.json()["graph"]["nodes"][1]["config"]["fields"][0]["value"] == "{{inputs.input}}"
    restored = await client.post(
        f"{base(workspace)}/flows/{flow['id']}/versions/1/restore", headers=admin.headers
    )
    assert (
        restored.json()["graph"]["nodes"][1]["config"]["fields"][0]["value"] == "{{inputs.input}}"
    )
    assert restored.json()["published_version"] == 2
    broken = copy.deepcopy(graph)
    broken["edges"] = []
    current = restored.json()["draft_revision"]
    await client.put(
        f"{base(workspace)}/flows/{flow['id']}/draft",
        json={"graph": broken, "base_revision": current},
        headers=admin.headers,
    )
    refused = await client.post(
        f"{base(workspace)}/flows/{flow['id']}/publish", json={}, headers=admin.headers
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "invalid_flow"


async def test_import_export_and_duplicate(client: httpx.AsyncClient, admin: Actor) -> None:
    workspace = await new_workspace(client, admin)
    flow = await create_flow(
        client, admin, workspace, name="Research", template="research-brief", tags=["research"]
    )
    exported = await client.get(
        f"{base(workspace)}/flows/{flow['id']}/export", headers=admin.headers
    )
    document = exported.json()
    assert document["format"] == "agentstudio.flow"
    other = await new_workspace(client, admin)
    imported = await client.post(
        f"{base(other)}/flows/import", json=document, headers=admin.headers
    )
    assert imported.status_code == 201
    assert any(issue["code"] == "unknown_knowledge_base" for issue in imported.json()["issues"])
    copy_ = await client.post(
        f"{base(workspace)}/flows/{flow['id']}/duplicate", headers=admin.headers
    )
    assert copy_.json()["name"] == "Research (copy)"
    script = await client.get(
        f"{base(workspace)}/flows/{flow['id']}/export/python", headers=admin.headers
    )
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/x-python")
    assert script.headers["content-disposition"] == 'attachment; filename="research.py"'
    compile(script.text, "research.py", "exec")
    unpublished = await client.get(
        f"{base(workspace)}/flows/{flow['id']}/export?version=published", headers=admin.headers
    )
    assert unpublished.status_code == 409


async def test_viewers_read_but_cannot_change_flows(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    flow = await create_flow(client, admin, workspace)
    viewer = await add_member(client, admin, workspace, "viewer")
    assert (
        await client.get(f"{base(workspace)}/flows/{flow['id']}", headers=viewer.headers)
    ).status_code == 200
    assert (
        await client.patch(
            f"{base(workspace)}/flows/{flow['id']}", json={"name": "x"}, headers=viewer.headers
        )
    ).status_code == 403
    assert (
        await client.delete(f"{base(workspace)}/flows/{flow['id']}", headers=viewer.headers)
    ).status_code == 403
    assert (
        await client.delete(f"{base(workspace)}/flows/{flow['id']}", headers=admin.headers)
    ).status_code == 204
    assert (
        await client.get(f"{base(workspace)}/flows/{flow['id']}", headers=admin.headers)
    ).status_code == 404
