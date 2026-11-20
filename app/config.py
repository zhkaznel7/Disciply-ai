import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    environment: Literal["development", "test", "production"] = "production"
    database_url: SecretStr
    jwt_secret: SecretStr
    jwt_issuer: str = "disciply-api"
    jwt_audience: str = "disciply-web"
    access_seconds: int = Field(600, ge=1, le=900)
    refresh_seconds: int = Field(2_592_000, ge=60, le=7_776_000)
    cookie_secure: bool = True
    cors_origins: list[str]
    max_body_bytes: int = Field(16_384, ge=1024, le=1_048_576)
    auth_attempts_per_minute: int = Field(20, ge=1, le=1000)

    @model_validator(mode="after")
    def check_security(self):
        secret = self.jwt_secret.get_secret_value()
        if not re.fullmatch(r"[0-9a-fA-F]{64}", secret) or len(set(secret.lower())) < 10:
            raise ValueError("JWT_SECRET must be a randomly generated 64-character hex string")
        try:
            db = make_url(self.database_url.get_secret_value())
        except (ValueError, TypeError, ArgumentError):
            raise ValueError("DATABASE_URL must be a valid SQLAlchemy URL") from None
        if db.drivername != "postgresql+asyncpg" or not db.database:
            raise ValueError("DATABASE_URL must specify a PostgreSQL database using asyncpg")
        if self.refresh_seconds <= self.access_seconds:
            raise ValueError("REFRESH_SECONDS must exceed ACCESS_SECONDS")
        if not self.jwt_issuer.strip() or not self.jwt_audience.strip():
            raise ValueError("JWT issuer and audience are required")
        production = self.environment == "production"
        if production and not self.cookie_secure:
            raise ValueError("Production requires Secure cookies")
        if not self.cors_origins:
            raise ValueError("Configure at least one trusted browser origin")
        for origin in self.cors_origins:
            url = urlsplit(origin)
            if (
                url.scheme not in (("https",) if production else ("http", "https"))
                or not url.hostname or url.username is not None
                or origin != f"{url.scheme}://{url.netloc}"
                or "*" in origin or any(char.isspace() for char in origin)
            ):
                raise ValueError("CORS_ORIGINS must contain exact browser origins")
            _ = url.port
        return self
