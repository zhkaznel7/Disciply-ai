import secrets

import pytest
from pydantic import ValidationError

from app.config import Settings
from conftest import ORIGIN


def test_production_configuration():
    values = {
        "environment": "production",
        "database_url": "postgresql+asyncpg://user:password@db/disciply",
        "jwt_secret": secrets.token_hex(32),
        "cors_origins": [ORIGIN],
        "cookie_secure": True,
    }
    assert Settings(_env_file=None, **values).environment == "production"
    for unsafe in (
        {"jwt_secret": "x" * 64},
        {"cookie_secure": False},
        {"cors_origins": ["http://localhost:8000"]},
        {"cors_origins": ["https://*.example.com"]},
    ):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{**values, **unsafe})
