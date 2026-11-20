from datetime import date, timedelta
from fractions import Fraction
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app import productivity_repository as repo
from app.errors import APIError
from app.focus_analytics import FocusAnalytics, MICROSECONDS_PER_MINUTE
from app.focus_calendar import validate_dates
from app.focus_service import now_utc
from app.habit_schedule import daily_status, progress
from app.productivity_schemas import (
    DisciplineScore, ProductivityDay, ProductivityRange, ReflectionWrite, ScoreComponent,
)
from app.repositories import user_timezone

FOCUS_TARGET_MINUTES = 25
MAX_REPORT_DAYS = 31


def score(tasks: tuple[int, int], habits: tuple[int, int], focus_us: int) -> DisciplineScore:
    active = bool(tasks[0] or habits[0] or focus_us)
    focus_target = FOCUS_TARGET_MINUTES * MICROSECONDS_PER_MINUTE
    inputs = {
        "tasks": (40, bool(tasks[0]), Fraction(tasks[1], tasks[0]) if tasks[0] else Fraction()),
        "habits": (40, bool(habits[0]), Fraction(habits[1], habits[0]) if habits[0] else Fraction()),
        "focus": (20, active, Fraction(min(focus_us, focus_target), focus_target)),
    }
    weight = sum(weight for weight, included, _ in inputs.values() if included)
    weighted = sum(weight * ratio for weight, included, ratio in inputs.values() if included)
    value = int(100 * weighted / weight + Fraction(1, 2)) if weight else None
    return DisciplineScore(
        value=value, focus_target_minutes=FOCUS_TARGET_MINUTES,
        **{name: ScoreComponent(weight=weight, applicable=included,
                                completion_percentage=round(float(100 * ratio), 2))
           for name, (weight, included, ratio) in inputs.items()},
    )


class ProductivityService:
    def __init__(self, db: AsyncSession, owner: UUID):
        self.db = db
        self.owner = owner

    async def _calendar(self) -> tuple[ZoneInfo, date]:
        zone = await user_timezone(self.db, self.owner)
        return zone, now_utc().astimezone(zone).date()

    @staticmethod
    def _validate(start: date, end: date, today: date) -> None:
        validate_dates(start, end)
        if end > today or (end - start).days >= MAX_REPORT_DAYS:
            raise APIError(422, "invalid_input", "Use up to 31 days ending on or before local today.")

    async def _report(
        self, start: date, end: date, today: date, zone: ZoneInfo,
    ) -> ProductivityRange:
        self._validate(start, end, today)
        task_counts = await repo.scheduled_tasks(self.db, self.owner, start, end, zone.key)
        monday = start - timedelta(days=start.weekday())
        habits = await repo.habits_and_counts(self.db, self.owner, start, monday, end, zone.key)
        focus, _ = await FocusAnalytics(self.db, self.owner).daily_totals(start, end, zone)
        reflected = await repo.reflected_dates(self.db, self.owner, start, end)

        days = []
        for day, totals in focus.items():
            scheduled = completed = 0
            for habit, archive_date, counts in habits:
                if archive_date is not None and archive_date <= day:
                    continue
                _, due, met = daily_status(habit, counts, day)
                scheduled += due
                completed += due and met
            task = task_counts.get(day, (0, 0))
            days.append(ProductivityDay(
                date=day, timezone=zone.key, tasks=progress(task[1], task[0]),
                habits=progress(completed, scheduled), focus=totals.view(),
                discipline_score=score(task, (scheduled, completed), totals.focus),
                has_evening_reflection=day in reflected,
            ))
        return ProductivityRange(timezone=zone.key, from_date=start, to_date=end, days=days)

    async def daily(self, day: date | None) -> ProductivityDay:
        zone, today = await self._calendar()
        day = day or today
        report = await self._report(day, day, today, zone)
        return report.days[0]

    async def range(self, start: date, end: date) -> ProductivityRange:
        zone, today = await self._calendar()
        return await self._report(start, end, today, zone)


class ReflectionService:
    def __init__(self, db: AsyncSession, owner: UUID):
        self.db = db
        self.owner = owner

    async def _validate(self, day: date) -> None:
        zone = await user_timezone(self.db, self.owner)
        validate_dates(day, day)
        if day > now_utc().astimezone(zone).date():
            raise APIError(422, "invalid_input", "Reflection date cannot be in the future.")

    async def get(self, day: date):
        await self._validate(day)
        reflection = await repo.reflection(self.db, self.owner, day)
        if reflection is None:
            raise APIError(404, "not_found", "Resource not found.")
        return reflection

    async def save(self, day: date, body: ReflectionWrite):
        await self._validate(day)
        result = await repo.save_reflection(self.db, self.owner, day, body.notes, body.mood)
        await self.db.commit()
        return result

    async def delete(self, day: date):
        await self._validate(day)
        if not await repo.delete_reflection(self.db, self.owner, day):
            raise APIError(404, "not_found", "Resource not found.")
        await self.db.commit()
