from datetime import date, datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AIUsage, EveningReflection, Goal, Task


async def usage(db: AsyncSession, owner: UUID, day: date, *, lock: bool = False) -> AIUsage | None:
    if lock:
        await db.execute(
            insert(AIUsage).values(user_id=owner, usage_on=day)
            .on_conflict_do_nothing(index_elements=[AIUsage.user_id, AIUsage.usage_on])
        )
    query = sa.select(AIUsage).where(AIUsage.user_id == owner, AIUsage.usage_on == day)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(query)


async def goals(db: AsyncSession, owner: UUID) -> tuple[int, float | None]:
    count, average = (await db.execute(
        sa.select(sa.func.count(), sa.func.avg(Goal.progress))
        .where(Goal.user_id == owner, Goal.completed_at.is_(None))
    )).one()
    return count, round(float(average), 2) if average is not None else None


async def reflection_mood(db: AsyncSession, owner: UUID, start: date, end: date):
    count, average = (await db.execute(
        sa.select(sa.func.count(EveningReflection.mood), sa.func.avg(EveningReflection.mood))
        .where(EveningReflection.user_id == owner, EveningReflection.reflected_on.between(start, end))
    )).one()
    return {"entries": count, "average_mood": round(float(average), 2) if count else None}


async def candidate_tasks(db: AsyncSession, owner: UUID, today: date, now: datetime, tomorrow: datetime):
    due_today = sa.and_(Task.due_at.is_not(None), Task.due_at < tomorrow)
    rank = sa.case(
        (Task.due_at <= now, 0), (due_today, 1), (Task.scheduled_on == today, 2), else_=3,
    )
    query = (
        sa.select(Task, sa.func.count().over())
        .where(Task.user_id == owner, Task.completed_at.is_(None),
               sa.or_(Task.scheduled_on.is_(None), Task.scheduled_on <= today, due_today))
        .order_by(rank, Task.priority.desc(), Task.due_at.asc().nulls_last(),
                  Task.scheduled_start_at.asc().nulls_last(), Task.created_at, Task.id)
        .limit(20)
    )
    rows = (await db.execute(query)).all()
    return [task for task, _ in rows], rows[0][1] if rows else 0
