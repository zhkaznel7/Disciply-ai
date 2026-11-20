from datetime import date
from typing import TypeVar
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Goal, Project, Task
from app.planning_schemas import GoalFilters, Pagination, ProjectFilters, TaskFilters

Record = TypeVar("Record", Goal, Project, Task)


async def owned(
    db: AsyncSession, model: type[Record], owner: UUID, record_id: UUID, *, lock: bool = False
) -> Record | None:
    statement = sa.select(model).where(model.user_id == owner, model.id == record_id)
    if lock:
        statement = statement.with_for_update()
    return await db.scalar(statement)


async def page(db: AsyncSession, statement, filters: Pagination):
    rows = list(await db.scalars(statement.offset(filters.offset).limit(filters.limit + 1)))
    return rows[:filters.limit], len(rows) > filters.limit


async def goals(db: AsyncSession, owner: UUID, filters: GoalFilters):
    query = sa.select(Goal).where(Goal.user_id == owner)
    if filters.status is not None:
        query = query.where(Goal.completed_at.is_not(None) if filters.status == "completed"
                            else Goal.completed_at.is_(None))
    if filters.target_on is not None:
        query = query.where(Goal.target_on == filters.target_on)
    return await page(db, query.order_by(Goal.created_at.desc(), Goal.id), filters)


async def projects(db: AsyncSession, owner: UUID, filters: ProjectFilters):
    query = sa.select(Project).where(Project.user_id == owner)
    if filters.status is not None:
        query = query.where(Project.archived_at.is_not(None) if filters.status == "archived"
                            else Project.archived_at.is_(None))
    return await page(db, query.order_by(Project.created_at.desc(), Project.id), filters)


async def tasks(db: AsyncSession, owner: UUID, filters: TaskFilters):
    query = sa.select(Task).where(Task.user_id == owner)
    for column, value in (
        (Task.priority, filters.priority), (Task.project_id, filters.project_id),
        (Task.scheduled_on, filters.scheduled_on),
    ):
        if value is not None:
            query = query.where(column == value)
    if filters.status is not None:
        query = query.where(Task.completed_at.is_not(None) if filters.status == "completed"
                            else Task.completed_at.is_(None))
    if filters.goal_id is not None:
        inherited = sa.exists().where(
            Project.user_id == owner, Project.id == Task.project_id,
            Project.goal_id == filters.goal_id,
        )
        query = query.where(sa.or_(
            Task.goal_id == filters.goal_id, sa.and_(Task.goal_id.is_(None), inherited),
        ))
    if filters.overdue is not None:
        overdue = sa.and_(
            Task.completed_at.is_(None), Task.due_at.is_not(None), Task.due_at < sa.func.now()
        )
        query = query.where(overdue if filters.overdue else ~overdue)
    return await page(db, query.order_by(Task.created_at.desc(), Task.id), filters)


async def scheduled(
    db: AsyncSession, owner: UUID, start: date, end: date, pagination: Pagination
) -> tuple[list[Task], bool]:
    statement = (
        sa.select(Task).where(Task.user_id == owner, Task.scheduled_on.between(start, end))
        .order_by(Task.scheduled_on, Task.scheduled_start_at.asc().nulls_last(),
                  Task.priority.desc(), Task.created_at, Task.id)
    )
    return await page(db, statement, pagination)
