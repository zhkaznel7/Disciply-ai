from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app import habit_repository as repo
from app.errors import APIError
from app.habit_schedule import is_scheduled, monday, month_end, period_progress, progress, streaks
from app.habit_schemas import (
    DayStatus, HabitCreate, HabitFilters, HabitStats, HabitUpdate, HabitView, LogCreate,
    LogFilters, LogUpdate, LogView, PeriodHabit, Summary,
)
from app.models import Habit, HabitLog
from app.planning_schemas import Page, Pagination
from app.repositories import user_timezone


def missing():
    return APIError(404, "not_found", "Resource not found.")


def invalid(message: str):
    return APIError(422, "invalid_input", message)


def week_bounds(today: date) -> tuple[date, date]:
    first = monday(today.toordinal())
    return date.fromordinal(first), date.fromordinal(min(first + 6, date.max.toordinal()))


class HabitService:
    def __init__(self, db: AsyncSession, owner: UUID):
        self.db = db
        self.owner = owner

    async def get(self, habit_id: UUID, *, lock: bool = False) -> Habit:
        habit = await repo.habit(self.db, self.owner, habit_id, lock=lock)
        if habit is None:
            raise missing()
        return habit

    async def list(self, filters: HabitFilters) -> Page[HabitView]:
        items, more = await repo.habits(self.db, self.owner, filters.status, filters)
        return Page[HabitView](items=items, limit=filters.limit, offset=filters.offset, has_more=more)

    async def save(self, payload: HabitCreate | HabitUpdate, habit_id: UUID | None = None) -> Habit:
        values = payload.model_dump(exclude_unset=True)
        if habit_id is None:
            starts_on = values.pop("starts_on", None)
            if starts_on is None:
                starts_on = datetime.now(await user_timezone(self.db, self.owner)).date()
            habit = Habit(user_id=self.owner, frequency="daily", weekday_mask=0,
                          target_count=1, starts_on=starts_on)
        else:
            habit = await self.get(habit_id, lock=True)

        status = values.pop("status", None)
        if "weekdays" in values:
            weekdays = values.pop("weekdays")
            if len(weekdays) != len(set(weekdays)):
                raise invalid("Weekdays must be distinct.")
            values["weekday_mask"] = sum(1 << day for day in weekdays)

        frequency = values.get("frequency", habit.frequency)
        mask = values.get("weekday_mask", habit.weekday_mask)
        quota = values.get("weekly_target", habit.weekly_target)
        if ((frequency == "weekdays") != bool(mask)
                or (frequency == "weekly") != (quota is not None)):
            raise invalid("Provide weekdays only for weekdays frequency and a weekly target only for weekly frequency.")
        schedule_fields = {"frequency", "weekday_mask", "weekly_target", "target_count", "starts_on"}
        if (habit_id is not None
                and any(name in values and values[name] != getattr(habit, name) for name in schedule_fields)
                and await repo.has_logs(self.db, self.owner, habit.id)):
            raise APIError(409, "habit_schedule_locked", "Habit schedule and targets are fixed while logs exist.")

        for name, value in values.items():
            setattr(habit, name, value)
        if status is not None:
            habit.archived_at = (habit.archived_at or datetime.now(UTC)) if status == "archived" else None
        self.db.add(habit)
        await self.db.flush()
        await self.db.refresh(habit)
        await self.db.commit()
        return habit

    async def delete(self, habit_id: UUID) -> None:
        habit = await self.get(habit_id, lock=True)
        await self.db.delete(habit)
        await self.db.commit()

    @staticmethod
    def require_active(habit: Habit):
        if habit.archived_at is not None:
            raise APIError(409, "habit_archived", "Restore the habit before changing its logs.")

    async def add_log(self, habit_id: UUID, payload: LogCreate) -> HabitLog:
        habit = await self.get(habit_id, lock=True)
        self.require_active(habit)
        today = datetime.now(await user_timezone(self.db, self.owner)).date()
        day = payload.date if payload.date is not None else today
        if day > today or not is_scheduled(habit, day):
            raise invalid("Log date must be a scheduled date from the habit start through local today.")
        log = await repo.create_log(self.db, self.owner, habit.id, day, payload.count)
        if log is None:
            raise APIError(409, "habit_log_exists", "A completion log already exists for that date.")
        await self.db.commit()
        return log

    async def logs(self, habit_id: UUID, filters: LogFilters) -> Page[LogView]:
        await self.get(habit_id)
        if filters.from_date and filters.to_date and filters.from_date > filters.to_date:
            raise invalid("Log start date must be on or before the end date.")
        items, more = await repo.logs(
            self.db, self.owner, habit_id, filters.from_date, filters.to_date, filters
        )
        return Page[LogView](items=items, limit=filters.limit, offset=filters.offset, has_more=more)

    async def _editable_log(self, habit_id: UUID, log_id: UUID) -> HabitLog:
        habit = await self.get(habit_id, lock=True)
        log = await repo.log(self.db, self.owner, habit_id, log_id)
        if log is None:
            raise missing()
        self.require_active(habit)
        return log

    async def update_log(self, habit_id: UUID, log_id: UUID, payload: LogUpdate) -> HabitLog:
        log = await self._editable_log(habit_id, log_id)
        log.count = payload.count
        await self.db.flush()
        await self.db.refresh(log)
        await self.db.commit()
        return log

    async def delete_log(self, habit_id: UUID, log_id: UUID) -> None:
        log = await self._editable_log(habit_id, log_id)
        await self.db.delete(log)
        await self.db.commit()

    async def stats(self, habit_id: UUID) -> HabitStats:
        habit = await self.get(habit_id)
        timezone = await user_timezone(self.db, self.owner)
        today = datetime.now(timezone).date()
        if habit.archived_at is not None:
            today = min(today, habit.archived_at.astimezone(timezone).date())
        qualified = await repo.completed_dates(self.db, self.owner, habit, today)
        current, longest = streaks(habit, qualified, today)
        overall = period_progress(habit, qualified, habit.starts_on, date.max, today)
        return HabitStats(
            habit=habit, timezone=timezone.key, date=today,
            streak_unit="weeks" if habit.frequency == "weekly" else "days",
            current_streak=current, longest_streak=longest,
            last_completed_date=qualified[-1] if qualified else None,
            completion_percentage=overall.completion_percentage,
            weekly=period_progress(habit, qualified, *week_bounds(today), today),
            monthly=period_progress(habit, qualified, today.replace(day=1), month_end(today), today),
        )

    @staticmethod
    def _day_status(habit: Habit, counts: dict[date, int], today: date) -> DayStatus:
        count = counts.get(today, 0)
        scheduled = is_scheduled(habit, today)
        if scheduled and habit.frequency == "weekly":
            start, end = week_bounds(today)
            quota = min(habit.weekly_target, (end - max(start, habit.starts_on)).days + 1)
            met_before_today = sum(day >= max(start, habit.starts_on) and day < today
                                   and value >= habit.target_count for day, value in counts.items())
            scheduled = met_before_today < quota
        return DayStatus(habit=habit, count=count, scheduled=scheduled,
                         completed=is_scheduled(habit, today) and count >= habit.target_count)

    async def _snapshot(self, pagination: Pagination | None, include_month: bool):
        timezone = await user_timezone(self.db, self.owner)
        today = datetime.now(timezone).date()
        habits, more = await repo.habits(self.db, self.owner, "active", pagination)
        first, _ = week_bounds(today)
        if include_month:
            first = min(first, today.replace(day=1))
        ids = [habit.id for habit in habits] if pagination is not None else None
        counts = await repo.period_counts(self.db, self.owner, ids, first, today)
        return timezone.key, today, habits, counts, more

    async def today(self, pagination: Pagination) -> Page[DayStatus]:
        _, today, habits, counts, more = await self._snapshot(pagination, False)
        items = [self._day_status(habit, counts.get(habit.id, {}), today) for habit in habits]
        return Page[DayStatus](items=items, limit=pagination.limit, offset=pagination.offset, has_more=more)

    @staticmethod
    def _period(habit: Habit, counts: dict[date, int], today: date, period: Literal["weekly", "monthly"]):
        bounds = week_bounds(today) if period == "weekly" else (today.replace(day=1), month_end(today))
        qualified = [day for day, count in counts.items() if count >= habit.target_count]
        return period_progress(habit, qualified, *bounds, today)

    async def period(self, pagination: Pagination, period: Literal["weekly", "monthly"]) -> Page[PeriodHabit]:
        _, today, habits, counts, more = await self._snapshot(pagination, period == "monthly")
        items = [PeriodHabit(habit=habit, progress=self._period(habit, counts.get(habit.id, {}), today, period))
                 for habit in habits]
        return Page[PeriodHabit](items=items, limit=pagination.limit, offset=pagination.offset, has_more=more)

    async def summary(self) -> Summary:
        timezone, today, habits, counts, _ = await self._snapshot(None, True)
        statuses = [self._day_status(habit, counts.get(habit.id, {}), today) for habit in habits]
        weekly = [self._period(habit, counts.get(habit.id, {}), today, "weekly") for habit in habits]
        monthly = [self._period(habit, counts.get(habit.id, {}), today, "monthly") for habit in habits]
        return Summary(
            timezone=timezone, date=today, total_active_habits=len(habits),
            completed_habits_today=sum(status.completed for status in statuses),
            today=progress(sum(status.completed and status.scheduled for status in statuses),
                           sum(status.scheduled for status in statuses)),
            weekly=progress(sum(item.completed for item in weekly), sum(item.target for item in weekly)),
            monthly=progress(sum(item.completed for item in monthly), sum(item.target for item in monthly)),
        )
