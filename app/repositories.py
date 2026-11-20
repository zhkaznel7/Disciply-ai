from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RefreshCredential, RefreshSession, User


async def add_user(db: AsyncSession, email: str, password_hash: str) -> User | None:
    statement = (
        insert(User).values(email=email, password_hash=password_hash)
        .on_conflict_do_nothing(index_elements=[User.email]).returning(User)
    )
    return await db.scalar(statement)


async def user_by_email(db: AsyncSession, email: str) -> User | None:
    return await db.scalar(select(User).where(User.email == email))


async def lock_session(
    db: AsyncSession, session_id: UUID, user_id: UUID | None = None
) -> RefreshSession | None:
    statement = select(RefreshSession).where(RefreshSession.id == session_id)
    if user_id is not None:
        statement = statement.where(RefreshSession.user_id == user_id)
    return await db.scalar(statement.with_for_update())


async def lock_by_digest(
    db: AsyncSession, digest: bytes
) -> tuple[RefreshSession, RefreshCredential] | None:
    session_id = await db.scalar(
        select(RefreshCredential.session_id).where(RefreshCredential.digest == digest)
    )
    if session_id is None:
        return None
    session = await lock_session(db, session_id)
    if session is None:
        return None
    # Read after obtaining the family lock so a waiting request sees the committed rotation.
    credential = await db.scalar(
        select(RefreshCredential).where(RefreshCredential.digest == digest)
    )
    if credential is None:
        return None
    return session, credential


async def active_user(db: AsyncSession, user_id: UUID, session_id: UUID) -> User | None:
    return await db.scalar(
        select(User).join(RefreshSession, RefreshSession.user_id == User.id).where(
            User.id == user_id,
            RefreshSession.id == session_id,
            RefreshSession.revoked_at.is_(None),
            RefreshSession.expires_at > func.now(),
        )
    )
