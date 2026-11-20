from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app import repositories
from app.config import Settings
from app.errors import APIError, unauthorized
from app.models import RefreshCredential, RefreshSession, User, UserSettings
from app.schemas import Credentials
from app.security import AccessTokens, Passwords, new_refresh_token, refresh_digest


@dataclass(frozen=True, repr=False)
class SessionTokens:
    access: str
    refresh: str
    expires_at: datetime


class AuthService:
    def __init__(self, settings: Settings, passwords: Passwords, dummy_hash: str):
        self.settings = settings
        self.passwords = passwords
        self.dummy_hash = dummy_hash
        self.access = AccessTokens(settings)

    async def register(self, db: AsyncSession, credentials: Credentials) -> User:
        encoded = await self.passwords.hash(credentials.password.get_secret_value())
        async with db.begin():
            user = await repositories.add_user(db, credentials.email, encoded)
            if user is None:
                raise APIError(409, "registration_conflict", "Unable to register that account.")
            db.add(UserSettings(user_id=user.id))
        return user

    async def login(
        self, db: AsyncSession, credentials: Credentials
    ) -> tuple[User, SessionTokens]:
        async with db.begin():
            user = await repositories.user_by_email(db, credentials.email)
        encoded = user.password_hash if user else self.dummy_hash
        matches = await self.passwords.matches(encoded, credentials.password.get_secret_value())
        if user is None or not matches:
            raise unauthorized()
        async with db.begin():
            session = RefreshSession(
                user_id=user.id,
                expires_at=datetime.now(UTC) + timedelta(seconds=self.settings.refresh_seconds),
            )
            db.add(session)
            await db.flush()
            tokens = self._add_credential(db, session)
        return user, tokens

    def _add_credential(self, db: AsyncSession, session: RefreshSession) -> SessionTokens:
        refresh = new_refresh_token()
        db.add(RefreshCredential(session_id=session.id, digest=refresh_digest(refresh)))
        return SessionTokens(
            self.access.issue(session.user_id, session.id), refresh, session.expires_at
        )

    async def rotate(self, db: AsyncSession, token: str | None) -> SessionTokens:
        tokens = None
        async with db.begin():
            match = await self._lock_refresh(db, token)
            now = datetime.now(UTC)
            if match:
                session, credential = match
                if session.revoked_at is None and session.expires_at > now:
                    if credential.consumed_at is not None:
                        session.revoked_at = now
                    else:
                        credential.consumed_at = now
                        await db.flush()
                        tokens = self._add_credential(db, session)
        # A replay must commit revocation before returning an authentication error.
        if tokens is None:
            raise unauthorized()
        return tokens

    async def logout(
        self, db: AsyncSession, refresh: str | None, access: str | None
    ) -> None:
        async with db.begin():
            match = await self._lock_refresh(db, refresh)
            session = match[0] if match else None
            if session is None and (claims := self.access.read(access)):
                user_id, session_id = claims
                session = await repositories.lock_session(db, session_id, user_id)
            if session is not None and session.revoked_at is None:
                session.revoked_at = datetime.now(UTC)

    async def current_user(self, db: AsyncSession, access: str | None) -> User:
        claims = self.access.read(access)
        if claims and (user := await repositories.active_user(db, *claims)):
            return user
        raise unauthorized()

    @staticmethod
    async def _lock_refresh(
        db: AsyncSession, token: str | None
    ) -> tuple[RefreshSession, RefreshCredential] | None:
        if token and len(token) == 43 and token.isascii():
            return await repositories.lock_by_digest(db, refresh_digest(token))
        return None
