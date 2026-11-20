from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.middleware import RequestGuards
from conftest import ORIGIN


async def test_auth_quota_isolates_clients_and_ignores_untrusted_forwarding(settings):
    settings = settings.model_copy(update={"auth_attempts_per_minute": 1})
    app = FastAPI()
    app.add_middleware(RequestGuards, settings=settings)

    @app.post("/api/v1/auth/login", status_code=204)
    async def login():
        return None

    async def post(peer, forwarded):
        async with AsyncClient(
            transport=ASGITransport(app=app, client=(peer, 12345)), base_url=ORIGIN,
        ) as client:
            return await client.post(
                "/api/v1/auth/login", headers={"Origin": ORIGIN, "X-Forwarded-For": forwarded}
            )

    assert (await post("192.0.2.1", "192.0.2.2")).status_code == 204
    denied = await post("192.0.2.1", "192.0.2.3")
    assert denied.status_code == 429
    assert denied.headers["Retry-After"] == "60"
    assert (await post("192.0.2.2", "192.0.2.3")).status_code == 204
