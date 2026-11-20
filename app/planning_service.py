from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import planning_repository as repository
from app.errors import APIError
from app.models import Goal, Project, Task
from app.planning_repository import Record
from app.repositories import user_timezone
from app.planning_schemas import (
    DailyPlan, GoalCreate, GoalFilters, GoalUpdate, GoalView, Page,
    Pagination, PlannerDay, ProjectCreate, ProjectFilters, ProjectUpdate,
    ProjectView, TaskCreate, TaskFilters, TaskUpdate, TaskView, WeeklyPlan,
)


def not_found():
    return APIError(404, "not_found", "Resource not found.")


def invalid(message: str):
    return APIError(422, "invalid_input", message)


class PlanningService:
    def __init__(self, db: AsyncSession, owner: UUID):
        self.db = db
        self.owner = owner

    async def get(self, model: type[Record], record_id: UUID, *, lock: bool = False) -> Record:
        record = await repository.owned(self.db, model, self.owner, record_id, lock=lock)
        if record is None:
            raise not_found()
        return record

    async def delete(self, model: type[Record], record_id: UUID) -> None:
        record = await self.get(model, record_id, lock=True)
        await self.db.delete(record)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            if getattr(exc.orig, "sqlstate", None) == "23503":
                raise APIError(409, "resource_in_use", "Unlink related records before deleting.") from None
            raise

    async def _save(self, record: Record) -> Record:
        self.db.add(record)
        try:
            await self.db.flush()
            await self.db.refresh(record)
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            if getattr(exc.orig, "sqlstate", None) == "23503":
                raise not_found() from None
            raise
        return record

    @staticmethod
    def _changes(record: Record, values: dict) -> None:
        for name, value in values.items():
            setattr(record, name, value)

    async def goals(self, filters: GoalFilters) -> Page[GoalView]:
        items, more = await repository.goals(self.db, self.owner, filters)
        return Page[GoalView](items=items, limit=filters.limit, offset=filters.offset, has_more=more)

    async def save_goal(self, payload: GoalCreate | GoalUpdate, goal_id: UUID | None = None) -> Goal:
        goal = await self.get(Goal, goal_id, lock=True) if goal_id else Goal(user_id=self.owner)
        values = payload.model_dump(exclude_unset=True)
        status = values.pop("status", None)
        progress = values.pop("progress", None)
        if progress is None:
            previous = goal.progress if goal_id else 0
            progress = 100 if status == "completed" else (
                0 if status == "active" and previous == 100 else previous
            )
        if status is not None and (status == "completed") != (progress == 100):
            raise invalid("Goal status and progress must agree.")
        goal.progress = progress
        goal.completed_at = (goal.completed_at or datetime.now(UTC)) if progress == 100 else None
        self._changes(goal, values)
        return await self._save(goal)

    async def projects(self, filters: ProjectFilters) -> Page[ProjectView]:
        items, more = await repository.projects(self.db, self.owner, filters)
        return Page[ProjectView](items=items, limit=filters.limit, offset=filters.offset, has_more=more)

    async def save_project(
        self, payload: ProjectCreate | ProjectUpdate, project_id: UUID | None = None
    ) -> Project:
        project = (await self.get(Project, project_id, lock=True) if project_id
                   else Project(user_id=self.owner))
        values = payload.model_dump(exclude_unset=True)
        status = values.pop("status", None)
        if values.get("goal_id") is not None:
            await self.get(Goal, values["goal_id"])
        self._changes(project, values)
        if project.starts_on and project.target_on and project.target_on < project.starts_on:
            raise invalid("Project target date must be on or after its start date.")
        if status is not None:
            project.archived_at = (project.archived_at or datetime.now(UTC)) if status == "archived" else None
        return await self._save(project)

    async def tasks(self, filters: TaskFilters) -> Page[TaskView]:
        if filters.project_id is not None:
            await self.get(Project, filters.project_id)
        if filters.goal_id is not None:
            await self.get(Goal, filters.goal_id)
        items, more = await repository.tasks(self.db, self.owner, filters)
        return Page[TaskView](items=items, limit=filters.limit, offset=filters.offset, has_more=more)

    async def save_task(self, payload: TaskCreate | TaskUpdate, task_id: UUID | None = None) -> Task:
        task = await self.get(Task, task_id, lock=True) if task_id else Task(user_id=self.owner)
        values = payload.model_dump(exclude_unset=True)
        status = values.pop("status", None)
        if values.get("project_id") is not None:
            await self.get(Project, values["project_id"])
        if values.get("goal_id") is not None:
            await self.get(Goal, values["goal_id"])
        self._changes(task, values)
        if values.keys() & {"scheduled_on", "scheduled_start_at", "scheduled_end_at"}:
            await self._validate_schedule(task)
        if status is not None:
            task.completed_at = (task.completed_at or datetime.now(UTC)) if status == "completed" else None
        return await self._save(task)

    async def _timezone(self) -> ZoneInfo:
        return await user_timezone(self.db, self.owner)

    async def _validate_schedule(self, task: Task) -> None:
        start, end = task.scheduled_start_at, task.scheduled_end_at
        if end is not None and (start is None or end <= start):
            raise invalid("Scheduled end must follow a scheduled start.")
        if start is not None:
            with self.db.no_autoflush:
                timezone = await self._timezone()
            try:
                local_date = start.astimezone(timezone).date()
            except OverflowError:
                raise invalid("Scheduled start is outside the supported local date range.") from None
            if task.scheduled_on != local_date:
                raise invalid("Scheduled date must match the start in the account timezone.")

    async def daily(self, day: date | None, pagination: Pagination) -> DailyPlan:
        timezone = await self._timezone()
        day = day if day is not None else datetime.now(timezone).date()
        tasks, more = await repository.scheduled(self.db, self.owner, day, day, pagination)
        return DailyPlan(date=day, timezone=timezone.key, tasks=tasks,
                         limit=pagination.limit, offset=pagination.offset, has_more=more)

    async def weekly(self, day: date | None, pagination: Pagination) -> WeeklyPlan:
        timezone = await self._timezone()
        day = day if day is not None else datetime.now(timezone).date()
        monday = day - timedelta(days=day.weekday())
        try:
            by_day = {monday + timedelta(days=offset): [] for offset in range(7)}
        except OverflowError:
            raise invalid("Week extends beyond the supported date range.") from None
        tasks, more = await repository.scheduled(
            self.db, self.owner, monday, next(reversed(by_day)), pagination
        )
        for task in tasks:
            by_day[task.scheduled_on].append(task)
        return WeeklyPlan(
            start_date=monday, timezone=timezone.key,
            days=[PlannerDay(date=local_date, tasks=items) for local_date, items in by_day.items()],
            limit=pagination.limit, offset=pagination.offset, has_more=more,
        )
