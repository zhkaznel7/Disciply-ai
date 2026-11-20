import re
from ipaddress import ip_address
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", hide_input_in_errors=True, env_ignore_empty=True
    )

    environment: Literal["development", "test", "production"] = "production"
    database_url: SecretStr
    migration_database_url: SecretStr | None = None
    jwt_secret: SecretStr
    jwt_issuer: str = "disciply-api"
    jwt_audience: str = "disciply-web"
    access_seconds: int = Field(600, ge=1, le=900)
    refresh_seconds: int = Field(2_592_000, ge=60, le=7_776_000)
    cookie_secure: bool = True
    cors_origins: list[str]
    max_body_bytes: int = Field(16_384, ge=1024, le=1_048_576)
    auth_attempts_per_minute: int = Field(20, ge=1, le=1000)

    analytics_requests_per_minute: int = Field(60, ge=1, le=1000)
    ai_requests_per_minute: int = Field(20, ge=1, le=1000)
    trusted_proxy_ips: list[str] = Field(default_factory=list, max_length=16)
    db_pool_size: int = Field(5, ge=1, le=30)
    db_max_overflow: int = Field(5, ge=0, le=30)
    db_pool_timeout_seconds: float = Field(5, ge=1, le=30)
    db_connect_timeout_seconds: float = Field(5, ge=1, le=30)
    db_command_timeout_seconds: float = Field(20, ge=1, le=120)
    readiness_timeout_seconds: float = Field(2, ge=0.5, le=10)

    ai_enabled: bool = False
    ai_provider_url: str | None = None
    ai_model: str | None = None
    ai_api_key: SecretStr | None = None
    ai_timeout_seconds: float = Field(8, ge=1, le=20)
    ai_daily_requests: int = Field(20, ge=1, le=100)
    ai_daily_tokens: int = Field(24000, ge=0, le=1000000)
    ai_max_output_tokens: int = Field(256, ge=64, le=1024)

    @property
    def ai_configured(self) -> bool:
        return self.ai_enabled and bool(self.ai_api_key and self.ai_api_key.get_secret_value())

    @model_validator(mode="after")
    def check_security(self):
        secret = self.jwt_secret.get_secret_value()
        if not re.fullmatch(r"[0-9a-fA-F]{64}", secret) or len(set(secret.lower())) < 10:
            raise ValueError("JWT_SECRET must be a randomly generated 64-character hex string")
        for database_url in (self.database_url, self.migration_database_url):
            if database_url is None:
                continue
            try:
                db = make_url(database_url.get_secret_value())
            except (ValueError, TypeError, ArgumentError):
                raise ValueError("Database URLs must be valid SQLAlchemy URLs") from None
            if db.drivername != "postgresql+asyncpg" or not db.database:
                raise ValueError("Database URLs must specify a PostgreSQL database using asyncpg")
            if self.environment == "production" and (
                not db.host or not db.username or not db.password or len(db.password) < 16
                or db.password.lower() in {"passwordpassword", "changemechangeme", "postgrespostgres"}
            ):
                raise ValueError("Production database URLs require a host and strong role credentials")
        try:
            if any("%" in peer for peer in self.trusted_proxy_ips):
                raise ValueError
            self.trusted_proxy_ips = [str(ip_address(peer)) for peer in self.trusted_proxy_ips]
        except ValueError:
            raise ValueError("TRUSTED_PROXY_IPS must list literal proxy addresses") from None
        if self.refresh_seconds <= self.access_seconds:
            raise ValueError("REFRESH_SECONDS must exceed ACCESS_SECONDS")
        if not self.jwt_issuer.strip() or not self.jwt_audience.strip():
            raise ValueError("JWT issuer and audience are required")
        if self.ai_configured:
            url = urlsplit(self.ai_provider_url or "")
            if (
                url.scheme != "https" or not url.hostname or url.username is not None
                or url.query or url.fragment or any(c.isspace() for c in self.ai_provider_url)
                or not url.path.rstrip("/").endswith("/chat/completions")
            ):
                raise ValueError("AI_PROVIDER_URL must be an HTTPS chat/completions endpoint")
            _ = url.port
            if not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,120}", self.ai_model or ""):
                raise ValueError("Set AI_MODEL to an explicit provider model identifier")
            if not re.fullmatch(r"[\x21-\x7e]{1,512}", self.ai_api_key.get_secret_value()):
                raise ValueError("AI_API_KEY must be a valid bearer credential")
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
