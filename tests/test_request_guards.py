import asyncio

from httpx import ASGITransport, AsyncClient

from app.main import create_app
from conftest import ORIGIN


async def test_shared_auth_quota_ignores_untrusted_forwarding(settings, migrated):
    settings = settings.model_copy(update={"auth_attempts_per_minute": 1})
    apps = [create_app(settings), create_app(settings)]
    payload = {"email": "rate-limit@example.com", "password": "unmatched fixture"}

    async def post(app, peer, forwarded):
        async with AsyncClient(
            transport=ASGITransport(app=app, client=(peer, 12345)), base_url=ORIGIN,
        ) as client:
            return await client.post(
                "/api/v1/auth/login", json=payload,
                headers={"Origin": ORIGIN, "X-Forwarded-For": forwarded},
            )

    async with apps[0].router.lifespan_context(apps[0]), apps[1].router.lifespan_context(apps[1]):
        replies = await asyncio.gather(
            post(apps[0], "192.0.2.1", "192.0.2.2"),
            post(apps[1], "192.0.2.1", "192.0.2.3"),
        )
        assert sorted(response.status_code for response in replies) == [401, 429]
        denied = next(response for response in replies if response.status_code == 429)
        assert denied.headers["Retry-After"] == "60"
        assert (await post(apps[1], "192.0.2.2", "192.0.2.3")).status_code == 401
