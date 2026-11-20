from datetime import date
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EveningReflection, Habit, HabitLog, Task


async def scheduled_tasks(db: AsyncSession, owner: UUID, start: date, end: date, zone: str):
    completion_date = sa.cast(sa.func.timezone(zone, Task.completed_at), sa.Date)
    query = (
        sa.select(Task.scheduled_on, sa.func.count(),
                  sa.func.count().filter(completion_date <= Task.scheduled_on))
        .where(Task.user_id == owner, Task.scheduled_on.between(start, end))
        .group_by(Task.scheduled_on)
    )
    return {day: (int(total), int(completed)) for day, total, completed in await db.execute(query)}


async def habits_and_counts(
    db: AsyncSession, owner: UUID, first_day: date, first_monday: date, end: date, zone: str,
):
    archived_on = sa.cast(sa.func.timezone(zone, Habit.archived_at), sa.Date)
    query = (
        sa.select(Habit, HabitLog.logged_on, HabitLog.count, archived_on)
        .outerjoin(HabitLog, sa.and_(
            HabitLog.user_id == Habit.user_id, HabitLog.habit_id == Habit.id,
            HabitLog.logged_on.between(first_monday, end),
        ))
        .where(Habit.user_id == owner, Habit.starts_on <= end,
               sa.or_(Habit.archived_at.is_(None), archived_on > first_day))
    )
    result: dict[UUID, tuple[Habit, date | None, dict[date, int]]] = {}
    for habit, logged_on, count, archived in await db.execute(query):
        _, _, counts = result.setdefault(habit.id, (habit, archived, {}))
        if logged_on is not None:
            counts[logged_on] = count
    return result.values()


async def reflected_dates(db: AsyncSession, owner: UUID, start: date, end: date) -> set[date]:
    query = sa.select(EveningReflection.reflected_on).where(
        EveningReflection.user_id == owner, EveningReflection.reflected_on.between(start, end)
    )
    return set(await db.scalars(query))


def reflection_scope(owner: UUID, day: date):
    return (EveningReflection.user_id == owner, EveningReflection.reflected_on == day)


async def reflection(db: AsyncSession, owner: UUID, day: date):
    return await db.scalar(sa.select(EveningReflection).where(*reflection_scope(owner, day)))


async def save_reflection(
    db: AsyncSession, owner: UUID, day: date, notes: str, mood: int | None,
) -> EveningReflection:
    statement = insert(EveningReflection).values(
        user_id=owner, reflected_on=day, notes=notes, mood=mood
    )
    statement = statement.on_conflict_do_update(
        index_elements=[EveningReflection.user_id, EveningReflection.reflected_on],
        set_={"notes": statement.excluded.notes, "mood": statement.excluded.mood},
    )
    return (await db.scalars(statement.returning(EveningReflection))).one()


async def delete_reflection(db: AsyncSession, owner: UUID, day: date) -> bool:
    statement = sa.delete(EveningReflection).where(*reflection_scope(owner, day))
    return await db.scalar(statement.returning(EveningReflection.id)) is not None
