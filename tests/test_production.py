import json
import logging
from contextlib import asynccontextmanager

from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.rate_limit import fingerprint
from conftest import ORIGIN


async def test_readiness_liveness_and_failed_database(client, app, monkeypatch):
    assert (await client.get("/api/v1/health")).json() == {"status": "ok"}
    assert (await client.get("/api/v1/health/ready")).json() == {"status": "ready"}
    with monkeypatch.context() as patch:
        patch.setattr(app.state, "alembic_heads", frozenset({"missing"}))
        assert (await client.get("/api/v1/health/ready")).status_code == 503

    @asynccontextmanager
    async def unavailable():
        raise OSError("private database connection details")
        yield

    monkeypatch.setattr(app.state, "sessions", unavailable)
    assert (await client.get("/api/v1/health")).status_code == 200
    failure = await client.get("/api/v1/health/ready")
    assert failure.status_code == 503 and "private" not in failure.text
    gated = await client.get("/api/v1/analytics/daily")
    assert gated.status_code == 503 and "private" not in gated.text


async def test_cors_and_request_telemetry_do_not_log_untrusted_data(client, caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error.disciply")
    user_data = "private-correlation-value"
    invalid = await client.post(
        f"/api/v1/auth/login?debug={user_data}",
        headers={"X-Request-ID": user_data}, json={"password": user_data},
    )
    assert invalid.status_code == 422
    correlation = invalid.headers["X-Request-ID"]
    assert correlation != user_data and len(correlation) == 32
    assert invalid.headers["Access-Control-Allow-Origin"] == ORIGIN
    assert "X-Request-ID" in invalid.headers["Access-Control-Expose-Headers"]
    denied = await client.options(
        "/api/v1/reflections/2026-01-01",
        headers={"Origin": "https://attacker.invalid", "Access-Control-Request-Method": "PUT"},
    )
    assert denied.status_code == 400 and "Access-Control-Allow-Origin" not in denied.headers
    assert (await client.post("/api/v1/auth/login", json={}, headers={"Origin": "null"})).status_code == 403
    records = [json.loads(record.message) for record in caplog.records
               if record.name == "uvicorn.error.disciply"]
    found = next(record for record in records if record["request_id"] == correlation)
    assert found["status"] == 422 and found["duration_ms"] >= 0
    assert user_data not in caplog.text


async def test_analytics_and_ai_burst_limits(settings, migrated):
    settings = settings.model_copy(update={"analytics_requests_per_minute": 1, "ai_requests_per_minute": 1})
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app, client=("192.0.2.44", 12345)),
            base_url=ORIGIN, headers={"Origin": ORIGIN},
        ) as client:
            assert (await client.get("/api/v1/analytics/daily")).status_code == 401
            denied = await client.get("/api/v1/focus/daily")
            assert denied.status_code == 429 and denied.headers["Retry-After"] == "60"
            assert (await client.post("/api/v1/ai/coach", json={})).status_code == 401
            assert (await client.post("/api/v1/ai/coach", json={})).status_code == 429
            assert (await client.get("/api/v1/health")).status_code == 200


def test_peer_fingerprints_normalize_ipv4_mappings_and_ipv6_prefixes(settings):
    assert fingerprint("192.0.2.7", settings) == fingerprint("::ffff:192.0.2.7", settings)
    assert fingerprint("2001:db8:1::1", settings) == fingerprint("2001:db8:1::2", settings)
    assert fingerprint("2001:db8:2::1", settings) != fingerprint("2001:db8:1::2", settings)
