from datetime import date
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Habit, HabitLog
from app.planning_repository import page
from app.planning_schemas import Pagination


async def habit(db: AsyncSession, owner: UUID, habit_id: UUID, *, lock: bool = False):
    query = sa.select(Habit).where(Habit.user_id == owner, Habit.id == habit_id)
    return await db.scalar(query.with_for_update() if lock else query)


async def habits(db: AsyncSession, owner: UUID, status: str | None, pagination: Pagination | None):
    query = sa.select(Habit).where(Habit.user_id == owner)
    if status == "active":
        query = query.where(Habit.archived_at.is_(None))
    elif status == "archived":
        query = query.where(Habit.archived_at.is_not(None))
    query = query.order_by(Habit.created_at.desc(), Habit.id)
    if pagination is not None:
        return await page(db, query, pagination)
    return list(await db.scalars(query)), False


def owned_logs(owner: UUID, habit_id: UUID):
    return sa.select(HabitLog).where(HabitLog.user_id == owner, HabitLog.habit_id == habit_id)


async def has_logs(db: AsyncSession, owner: UUID, habit_id: UUID) -> bool:
    return bool(await db.scalar(sa.select(owned_logs(owner, habit_id).exists())))


async def log(db: AsyncSession, owner: UUID, habit_id: UUID, log_id: UUID):
    return await db.scalar(owned_logs(owner, habit_id).where(HabitLog.id == log_id))


async def create_log(db: AsyncSession, owner: UUID, habit_id: UUID, day: date, count: int):
    query = (
        insert(HabitLog).values(user_id=owner, habit_id=habit_id, logged_on=day, count=count)
        .on_conflict_do_nothing(index_elements=[HabitLog.user_id, HabitLog.habit_id, HabitLog.logged_on])
        .returning(HabitLog)
    )
    return await db.scalar(query)


async def logs(
    db: AsyncSession, owner: UUID, habit_id: UUID, start: date | None, end: date | None,
    pagination: Pagination,
):
    query = owned_logs(owner, habit_id)
    if start is not None:
        query = query.where(HabitLog.logged_on >= start)
    if end is not None:
        query = query.where(HabitLog.logged_on <= end)
    return await page(db, query.order_by(HabitLog.logged_on.desc()), pagination)


async def completed_dates(db: AsyncSession, owner: UUID, habit: Habit, through: date) -> list[date]:
    query = sa.select(HabitLog.logged_on).where(
        HabitLog.user_id == owner, HabitLog.habit_id == habit.id,
        HabitLog.logged_on.between(habit.starts_on, through), HabitLog.count >= habit.target_count,
    )
    return list(await db.scalars(query.order_by(HabitLog.logged_on)))


async def period_counts(
    db: AsyncSession, owner: UUID, habit_ids: list[UUID] | None, start: date, end: date,
) -> dict[UUID, dict[date, int]]:
    if habit_ids == []:
        return {}
    query = sa.select(HabitLog.habit_id, HabitLog.logged_on, HabitLog.count).where(
        HabitLog.user_id == owner,
        HabitLog.logged_on.between(start, end),
    )
    if habit_ids is None:
        query = query.join(Habit, (Habit.user_id == HabitLog.user_id) & (Habit.id == HabitLog.habit_id))
        query = query.where(Habit.archived_at.is_(None))
    else:
        query = query.where(HabitLog.habit_id.in_(habit_ids))
    result: dict[UUID, dict[date, int]] = {}
    for habit_id, day, count in await db.execute(query):
        result.setdefault(habit_id, {})[day] = count
    return result
