import httpx
import pytest

from agentstudio.integrations.sandbox import create_sandbox_app


@pytest.fixture
async def sandbox():  # type: ignore[no-untyped-def]
    transport = httpx.ASGITransport(app=create_sandbox_app())
    async with httpx.AsyncClient(transport=transport, base_url="https://sandbox.test") as client:
        yield client


async def test_contacts(sandbox: httpx.AsyncClient) -> None:
    found = await sandbox.get("/crm/contacts", params={"email": "Dana.Whitfield@globex.example"})
    assert found.status_code == 200
    assert found.json()["plan"] == "enterprise"
    missing = await sandbox.get("/crm/contacts", params={"email": "nobody@nowhere.example"})
    assert missing.status_code == 404
    assert missing.json()["error"] == "not_found"


async def test_companies_known_synthetic_and_personal(sandbox: httpx.AsyncClient) -> None:
    known = (
        await sandbox.get("/crm/companies/lookup", params={"email": "priya@initech.example"})
    ).json()
    assert (known["name"], known["employees"], known["source"]) == ("Initech", 480, "crm")
    first = (
        await sandbox.get("/crm/companies/lookup", params={"domain": "acme-widgets.example"})
    ).json()
    again = (
        await sandbox.get("/crm/companies/lookup", params={"domain": "acme-widgets.example"})
    ).json()
    assert first == again
    assert first["source"] == "synthetic"
    assert first["name"] == "Acme Widgets"
    personal = await sandbox.get("/crm/companies/lookup", params={"email": "someone@gmail.com"})
    assert personal.status_code == 404
    assert (await sandbox.get("/crm/companies/lookup")).status_code == 400


async def test_vendors_match_loosely_by_name(sandbox: httpx.AsyncClient) -> None:
    found = (
        await sandbox.get("/erp/vendors", params={"name": "ACME Office Supplies Limited"})
    ).json()
    assert found["vendor_id"] == "V-1001"
    assert found["approval_limit"] == 5000
    assert (
        await sandbox.get("/erp/vendors", params={"name": "Unknown Traders"})
    ).status_code == 404


async def test_tasks_get_stable_ids_and_rates_are_fixed(sandbox: httpx.AsyncClient) -> None:
    body = {"title": "Send the deck", "assignee": "Leo", "due": "Friday"}
    first = await sandbox.post("/tasks", json=body)
    second = await sandbox.post("/tasks", json=body)
    assert first.status_code == 201
    assert first.json() == second.json()
    assert first.json()["id"].startswith("TSK-")
    assert (await sandbox.post("/tasks", json={"title": ""})).status_code == 422
    rates = (await sandbox.get("/fx/rates", params={"base": "eur"})).json()
    assert rates["base"] == "EUR"
    assert rates["rates"]["USD"] == 1.087
    assert (await sandbox.get("/fx/rates", params={"base": "XYZ"})).status_code == 404
