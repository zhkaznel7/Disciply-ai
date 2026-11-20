import os
import secrets
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url

from app.config import Settings
from app.main import create_app

ORIGIN = "https://test.disciply.invalid"


@pytest.fixture(scope="session")
def settings():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated PostgreSQL database ending in _test")
    database = make_url(url).database
    if not database or not database.endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must name a dedicated database ending in _test")
    return Settings(
        _env_file=None, environment="test", database_url=url, jwt_secret=secrets.token_hex(32),
        cors_origins=[ORIGIN], cookie_secure=True, access_seconds=600, refresh_seconds=3600,
        auth_attempts_per_minute=100,
    )


@pytest.fixture(scope="session")
def migrated(settings):
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["settings"] = settings
    command.upgrade(config, "head")
    command.check(config)


@pytest.fixture
async def app(settings, migrated):
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as session:
        yield session
