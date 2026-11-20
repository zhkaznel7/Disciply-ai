import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from sqlalchemy import select

from app.models import RefreshCredential, User
from app.security import ACCESS_COOKIE, REFRESH_COOKIE, refresh_digest
from conftest import ORIGIN

AUTH = "/api/v1/auth"


def credentials():
    return {"email": f"user-{uuid4()}@example.com", "password": "an original test passphrase"}


async def register(client, account):
    response = await client.post(f"{AUTH}/register", json=account)
    assert response.status_code == 201, response.text
    return response.json()


async def login(client, account):
    response = await client.post(f"{AUTH}/login", json=account)
    assert response.status_code == 200, response.text
    return response


def cookies(**tokens):
    return {"Cookie": "; ".join(f"{key}={value}" for key, value in tokens.items())}


async def test_health_and_registration(client, app):
    assert (await client.get("/api/v1/health")).json() == {"status": "ok"}
    account = credentials()
    profile = await register(client, {**account, "email": account["email"].upper()})
    assert profile["email"] == account["email"]
    assert set(profile) == {"id", "email", "created_at"}
    response = await client.post(f"{AUTH}/register", json=account)
    assert response.status_code == 409
    async with app.state.sessions() as db:
        user = await db.get(User, UUID(profile["id"]))
        assert user.password_hash.startswith("$argon2id$")
        assert account["password"] not in user.password_hash


async def test_login_and_protected_profile(client, app):
    assert (await client.get(f"{AUTH}/me")).status_code == 401
    account = credentials()
    profile = await register(client, account)
    response = await login(client, account)
    assert response.json() == profile
    refresh = client.cookies[REFRESH_COOKIE]
    assert refresh not in response.text and client.cookies[ACCESS_COOKIE] not in response.text
    headers = response.headers.get_list("set-cookie")
    for header in headers:
        assert all(flag in header.lower() for flag in ("httponly", "secure", "samesite=lax"))
    assert any(f"{REFRESH_COOKIE}=" in header and f"Path={AUTH}" in header for header in headers)
    assert response.headers["Cache-Control"] == "no-store"
    access_claims = app.state.auth.access.read(client.cookies[ACCESS_COOKIE])
    async with app.state.sessions() as db:
        stored = await db.scalar(
            select(RefreshCredential).where(RefreshCredential.session_id == access_claims[1])
        )
        assert stored.digest == refresh_digest(refresh)
    assert (await client.get(f"{AUTH}/me")).json() == profile


async def test_invalid_credentials_are_generic(client):
    account = credentials()
    await register(client, account)
    known = await client.post(f"{AUTH}/login", json={**account, "password": "incorrect"})
    unknown = await client.post(f"{AUTH}/login", json={**credentials(), "password": "incorrect"})
    assert known.status_code == unknown.status_code == 401
    assert known.json() == unknown.json()
    assert "set-cookie" not in known.headers


async def test_expired_access(client, app):
    account = credentials()
    await register(client, account)
    await login(client, account)
    access = app.state.auth.access
    token = client.cookies[ACCESS_COOKIE]
    claims = jwt.decode(token, options={"verify_signature": False})
    claims["exp"] = datetime.now(UTC) - timedelta(seconds=10)
    expired = jwt.encode(claims, access.key, algorithm="HS256", headers={"typ": "at+jwt"})
    response = await client.get(f"{AUTH}/me", headers=cookies(**{ACCESS_COOKIE: expired}))
    assert response.status_code == 401
    assert (await client.post(f"{AUTH}/refresh")).status_code == 204
    assert (await client.get(f"{AUTH}/me")).status_code == 200


async def test_rotation_replay_revokes_active_family(client):
    account = credentials()
    await register(client, account)
    await login(client, account)
    old = client.cookies[REFRESH_COOKIE]
    response = await client.post(f"{AUTH}/refresh")
    assert response.status_code == 204 and response.content == b""
    assert old != client.cookies[REFRESH_COOKIE]
    replay = await client.post(f"{AUTH}/refresh", headers=cookies(**{REFRESH_COOKIE: old}))
    assert replay.status_code == 401
    assert (await client.get(f"{AUTH}/me")).status_code == 401
    assert (await client.post(f"{AUTH}/refresh")).status_code == 401


async def test_concurrent_refresh_revokes_replayed_family(client):
    account = credentials()
    await register(client, account)
    await login(client, account)
    original = cookies(**{REFRESH_COOKIE: client.cookies[REFRESH_COOKIE]})
    responses = await asyncio.gather(*[
        client.post(f"{AUTH}/refresh", headers=original) for _ in range(2)
    ])
    assert sorted(response.status_code for response in responses) == [204, 401]
    winner = next(response for response in responses if response.status_code == 204)
    headers = cookies(**{ACCESS_COOKIE: winner.cookies[ACCESS_COOKIE]})
    assert (await client.get(f"{AUTH}/me", headers=headers)).status_code == 401


async def test_logout_revokes_access_and_refresh(client):
    account = credentials()
    await register(client, account)
    await login(client, account)
    old = cookies(**{name: client.cookies[name] for name in (ACCESS_COOKIE, REFRESH_COOKIE)})
    response = await client.post(f"{AUTH}/logout")
    assert response.status_code == 204
    assert not client.cookies
    assert (await client.get(f"{AUTH}/me", headers=old)).status_code == 401
    assert (await client.post(f"{AUTH}/refresh", headers=old)).status_code == 401
    assert (await client.post(f"{AUTH}/logout")).status_code == 204


async def test_csrf_protection(client):
    account = credentials()
    unknown = await client.post(
        f"{AUTH}/register", json=account, headers={"Origin": "https://evil.invalid"}
    )
    assert unknown.status_code == 403
    assert "access-control-allow-origin" not in unknown.headers
    request = client.build_request("POST", f"{AUTH}/register", json=account)
    del request.headers["Origin"]
    assert (await client.send(request)).status_code == 403
    await register(client, account)
    await login(client, account)
    denied = await client.post(f"{AUTH}/logout", headers={"Origin": "null"})
    assert denied.status_code == 403
    assert (await client.get(f"{AUTH}/me")).status_code == 200
    preflight = await client.options(f"{AUTH}/login", headers={
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    assert preflight.headers["access-control-allow-origin"] == ORIGIN


async def test_invalid_input_and_streaming_body_limit(client, settings):
    for account in (
        {"email": "invalid", "password": "secret-do-not-return"},
        {**credentials(), "password": "short"},
        {**credentials(), "user_id": str(uuid4())},
    ):
        response = await client.post(f"{AUTH}/register", json=account)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_input"
        assert "secret-do-not-return" not in response.text

    async def chunks():
        yield b"x" * settings.max_body_bytes
        yield b"y"

    oversized = await client.post(f"{AUTH}/register", content=chunks())
    assert oversized.status_code == 413


async def test_profile_isolation(client, app):
    first, second = credentials(), credentials()
    first_profile = await register(client, first)
    second_profile = await register(client, second)
    await login(client, first)
    first_access = client.cookies[ACCESS_COOKIE]
    await login(client, second)
    assert (await client.get(f"{AUTH}/me", params={"user_id": first_profile["id"]})).json() == second_profile
    access = app.state.auth.access
    session_id = access.read(first_access)[1]
    mismatched = access.issue(UUID(second_profile["id"]), session_id)
    assert (await client.get(f"{AUTH}/me", headers=cookies(**{ACCESS_COOKIE: mismatched}))).status_code == 401
