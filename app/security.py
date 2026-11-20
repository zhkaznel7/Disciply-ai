import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from anyio import CapacityLimiter, to_thread
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.config import Settings

ACCESS_COOKIE = "disciply_access"
REFRESH_COOKIE = "disciply_refresh"
API_PATH = "/api/v1"
AUTH_PATH = f"{API_PATH}/auth"


class Passwords:
    def __init__(self):
        self.hasher = PasswordHasher()
        self.limiter = CapacityLimiter(2)

    async def hash(self, password: str) -> str:
        return await to_thread.run_sync(self.hasher.hash, password, limiter=self.limiter)

    async def matches(self, encoded: str, password: str) -> bool:
        try:
            return await to_thread.run_sync(
                self.hasher.verify, encoded, password, limiter=self.limiter
            )
        except VerifyMismatchError:
            return False


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def refresh_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


class AccessTokens:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.key = bytes.fromhex(settings.jwt_secret.get_secret_value())

    def issue(self, user_id: UUID, session_id: UUID) -> str:
        now = datetime.now(UTC)
        return jwt.encode({
            "sub": str(user_id),
            "sid": str(session_id),
            "iat": now,
            "exp": now + timedelta(seconds=self.settings.access_seconds),
            "iss": self.settings.jwt_issuer,
            "aud": self.settings.jwt_audience,
            "token_type": "access",
        }, self.key, algorithm="HS256", headers={"typ": "at+jwt"})

    def read(self, token: str | None) -> tuple[UUID, UUID] | None:
        if not token or len(token) > 2048:
            return None
        try:
            decoded = jwt.decode_complete(
                token, self.key, algorithms=["HS256"],
                issuer=self.settings.jwt_issuer, audience=self.settings.jwt_audience,
                options={
                    "require": ["sub", "sid", "iat", "exp", "iss", "aud", "token_type"],
                    "strict_aud": True,
                },
            )
            claims = decoded["payload"]
            if decoded["header"].get("typ") != "at+jwt" or claims["token_type"] != "access":
                return None
            return UUID(claims["sub"]), UUID(claims["sid"])
        except (jwt.InvalidTokenError, ValueError, TypeError, AttributeError, OverflowError):
            return None
