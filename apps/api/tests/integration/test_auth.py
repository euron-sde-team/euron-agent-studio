import httpx
from fastapi import FastAPI

from tests.integration.conftest import PASSWORD, WEB, Actor, add_member, login, new_workspace


async def test_first_account_is_admin_and_signup_then_closes(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    me = await client.get("/api/v1/auth/me", headers=admin.headers)
    assert me.status_code == 200
    assert me.json()["user"]["is_admin"] is True
    assert me.json()["workspaces"][0]["role"] == "owner"
    closed = await client.post(
        "/api/v1/auth/signup",
        json={"email": "late@northwind.example", "name": "Late", "password": PASSWORD},
    )
    assert closed.status_code == 403
    info = await client.get("/api/v1/system/info")
    assert info.json()["needs_setup"] is False
    assert info.json()["offline_only"] is True


async def test_wrong_passwords_are_refused_and_lock_the_account(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    member = await add_member(client, admin, workspace, "viewer")
    for _ in range(8):
        response = await client.post(
            "/api/v1/auth/login", json={"email": member.email, "password": "wrong password!"}
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"
    locked = await client.post(
        "/api/v1/auth/login", json={"email": member.email, "password": "wrong password!"}
    )
    assert locked.status_code == 429
    unknown = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@nowhere.example", "password": "x"}
    )
    assert unknown.status_code == 401


async def test_logout_revokes_the_token(client: httpx.AsyncClient, admin: Actor) -> None:
    session = await login(client, admin.email, PASSWORD)
    assert (await client.post("/api/v1/auth/logout", headers=session.headers)).status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=session.headers)).status_code == 401


async def test_password_change_signs_out_other_sessions(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    workspace = await new_workspace(client, admin)
    member = await add_member(client, admin, workspace, "editor")
    elsewhere = await login(client, member.email, member.password)
    weak = await client.post(
        "/api/v1/auth/password",
        json={"current_password": member.password, "new_password": "short"},
        headers=member.headers,
    )
    assert weak.status_code == 422
    wrong = await client.post(
        "/api/v1/auth/password",
        json={"current_password": "not my password", "new_password": "a much better passphrase"},
        headers=member.headers,
    )
    assert wrong.status_code == 401
    changed = await client.post(
        "/api/v1/auth/password",
        json={"current_password": member.password, "new_password": "a much better passphrase"},
        headers=member.headers,
    )
    assert changed.status_code == 200
    fresh = {"authorization": f"Bearer {changed.json()['token']}"}
    assert (await client.get("/api/v1/auth/me", headers=fresh)).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=elsewhere.headers)).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers=member.headers)).status_code == 401


async def test_cookie_sessions_need_the_web_origin_for_writes(app: FastAPI, admin: Actor) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as browser:
        signed_in = await browser.post(
            "/api/v1/auth/login", json={"email": admin.email, "password": PASSWORD}
        )
        assert signed_in.cookies.get("agentstudio_session")
        assert (await browser.get("/api/v1/auth/me")).status_code == 200
        forged = await browser.post(
            "/api/v1/workspaces",
            json={"name": "Forged"},
            headers={"origin": "https://evil.example"},
        )
        assert forged.status_code == 403
        assert forged.json()["error"]["code"] == "csrf"
        allowed = await browser.post(
            "/api/v1/workspaces", json={"name": "From the app"}, headers={"origin": WEB}
        )
        assert allowed.status_code == 201


async def test_profile_updates(client: httpx.AsyncClient, admin: Actor) -> None:
    response = await client.patch(
        "/api/v1/auth/me", json={"name": "Ava Admin"}, headers=admin.headers
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Ava Admin"
