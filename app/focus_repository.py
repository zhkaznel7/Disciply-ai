from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.focus_schemas import HistoryFilters
from app.models import FocusInterval, FocusSession, Task, User
from app.planning_repository import page


def owned(owner: UUID):
    return sa.select(FocusSession).where(FocusSession.user_id == owner)


async def get(db: AsyncSession, owner: UUID, session_id: UUID, *, lock: bool = False):
    query = owned(owner).where(FocusSession.id == session_id)
    return await db.scalar(query.with_for_update() if lock else query)


async def lock_owner(db: AsyncSession, owner: UUID) -> bool:
    query = sa.select(User.id).where(User.id == owner).with_for_update(key_share=True)
    return await db.scalar(query) is not None


async def current(db: AsyncSession, owner: UUID):
    return await db.scalar(owned(owner).where(FocusSession.ended_at.is_(None)))


async def has_task(db: AsyncSession, owner: UUID, task_id: UUID) -> bool:
    return await db.scalar(sa.select(Task.id).where(Task.user_id == owner, Task.id == task_id)) is not None


async def history(
    db: AsyncSession, owner: UUID, filters: HistoryFilters,
    zone: str | None,
):
    query = owned(owner)
    for column, value in ((FocusSession.status, filters.status),
                          (FocusSession.session_type, filters.session_type)):
        if value is not None:
            query = query.where(column == value)
    if zone is not None:
        local_date = sa.cast(sa.func.timezone(zone, FocusSession.started_at), sa.Date)
        if filters.from_date is not None:
            query = query.where(local_date >= filters.from_date)
        if filters.to_date is not None:
            query = query.where(local_date <= filters.to_date)
    return await page(db, query.order_by(FocusSession.started_at.desc(), FocusSession.id), filters)


async def latest_interval(db: AsyncSession, session_id: UUID):
    return await db.scalar(
        sa.select(FocusInterval).where(FocusInterval.session_id == session_id)
        .order_by(FocusInterval.started_at.desc(), FocusInterval.ended_at.desc().nulls_first())
        .limit(1)
    )


def running_microseconds(end):
    return sa.func.extract("epoch", end - FocusInterval.started_at) * 1_000_000


async def durations(db: AsyncSession, sessions: Sequence[FocusSession], now: datetime):
    if not sessions:
        return {}
    end = sa.func.coalesce(
        FocusInterval.ended_at, sa.func.greatest(now, FocusInterval.started_at)
    )
    query = (
        sa.select(FocusInterval.session_id, sa.func.sum(running_microseconds(end)))
        .where(FocusInterval.session_id.in_([session.id for session in sessions]))
        .group_by(FocusInterval.session_id)
    )
    return {session_id: int(value) for session_id, value in await db.execute(query)}


async def overlapping(db: AsyncSession, owner: UUID, start: datetime, end: datetime):
    query = (
        sa.select(FocusSession.session_type, FocusSession.task_id,
                  FocusInterval.started_at, FocusInterval.ended_at)
        .join(FocusInterval, FocusInterval.session_id == FocusSession.id)
        .where(FocusSession.user_id == owner, FocusSession.status == "completed",
               FocusSession.ended_at > start, FocusSession.started_at < end,
               FocusInterval.ended_at > start, FocusInterval.started_at < end)
    )
    return await db.execute(query)


async def completed_focus(db: AsyncSession, owner: UUID, start: datetime, end: datetime):
    query = (
        sa.select(FocusSession.ended_at, sa.func.sum(running_microseconds(FocusInterval.ended_at)))
        .join(FocusInterval, FocusInterval.session_id == FocusSession.id)
        .where(FocusSession.user_id == owner, FocusSession.status == "completed",
               FocusSession.session_type == "focus", FocusSession.ended_at >= start,
               FocusSession.ended_at < end)
        .group_by(FocusSession.id, FocusSession.ended_at)
    )
    return await db.execute(query)


async def recent_cycle(db: AsyncSession, owner: UUID):
    finished = owned(owner).where(FocusSession.status == "completed")
    order = (FocusSession.ended_at.desc(), FocusSession.id.desc())
    latest = await db.scalar(finished.order_by(*order).limit(1))
    last_long = await db.scalar(
        finished.where(FocusSession.session_type == "long_break").order_by(*order).limit(1)
    )
    query = sa.select(sa.func.count()).select_from(FocusSession).where(
        FocusSession.user_id == owner, FocusSession.status == "completed",
        FocusSession.session_type == "focus",
    )
    if last_long is not None:
        query = query.where(sa.tuple_(FocusSession.ended_at, FocusSession.id) >
                            sa.tuple_(last_long.ended_at, last_long.id))
    return latest.session_type if latest else None, await db.scalar(query)
