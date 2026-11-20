from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app import focus_repository as repo
from app.errors import APIError
from app.focus_calendar import DAY, day_windows, microseconds, validate_dates
from app.focus_schemas import (
    DEFAULT_MINUTES, LONG_BREAK_AFTER, DayMetrics, FocusSummary, Metrics, PeriodMetrics,
    Pomodoro, TaskFilters, TaskMetrics,
)
from app.focus_service import now_utc
from app.planning_schemas import Page
from app.repositories import user_timezone

MICROSECONDS_PER_MINUTE = 60_000_000


def minutes(value: int, count: int = 1) -> float:
    return round(value / (count * MICROSECONDS_PER_MINUTE), 6) if count else 0.0


@dataclass
class Totals:
    focus: int = 0
    breaks: int = 0
    completed: int = 0
    completed_time: int = 0

    def view(self) -> Metrics:
        return Metrics(
            focus_microseconds=self.focus, focus_minutes=minutes(self.focus),
            break_microseconds=self.breaks, break_minutes=minutes(self.breaks),
            completed_focus_sessions=self.completed,
            average_completed_focus_minutes=minutes(self.completed_time, self.completed),
        )


def aggregate(values) -> Metrics:
    result = Totals()
    for row in values:
        result.focus += row.focus
        result.breaks += row.breaks
        result.completed += row.completed
        result.completed_time += row.completed_time
    return result.view()


class FocusAnalytics:
    def __init__(self, db: AsyncSession, owner: UUID):
        self.db = db
        self.owner = owner

    async def _calendar(self):
        zone = await user_timezone(self.db, self.owner)
        return zone, now_utc().astimezone(zone).date()

    async def _totals(self, start: date, end: date, zone, *, task_report=False):
        totals = {start + timedelta(days=offset): Totals()
                  for offset in range((end - start).days + 1)}
        tasks = defaultdict(int)
        windows = day_windows(start, end, zone)
        if not windows:
            return totals, tasks
        begin, finish = windows[0][1], windows[-1][2]
        ends = [window[2] for window in windows]
        for kind, task_id, interval_start, interval_end in await repo.overlapping(
            self.db, self.owner, begin, finish
        ):
            index = bisect_right(ends, interval_start)
            while index < len(windows):
                day, left, right = windows[index]
                if left >= interval_end:
                    break
                amount = microseconds(min(right, interval_end) - max(left, interval_start))
                if amount > 0:
                    if kind == "focus":
                        totals[day].focus += amount
                        if task_report:
                            tasks[task_id] += amount
                    else:
                        totals[day].breaks += amount
                index += 1

        if not task_report:
            for ended_at, full_duration in await repo.completed_focus(
                self.db, self.owner, begin, finish
            ):
                row = totals.get(ended_at.astimezone(zone).date())
                if row is not None:
                    row.completed += 1
                    row.completed_time += int(full_duration)
        return totals, tasks

    async def summary(self) -> FocusSummary:
        zone, today = await self._calendar()
        monday = today - timedelta(days=today.weekday())
        first = today.replace(day=1)
        totals, _ = await self._totals(min(monday, first), today, zone)
        latest, count = await repo.recent_cycle(self.db, self.owner)
        recommendation = ("long_break" if count >= LONG_BREAK_AFTER else
                          "short_break" if latest == "focus" else "focus")
        return FocusSummary(
            timezone=zone.key, date=today, today=totals[today].view(),
            weekly=aggregate(totals[day] for day in totals if day >= monday),
            monthly=aggregate(totals[day] for day in totals if day >= first),
            pomodoro=Pomodoro(
                completed_focus_since_long_break=count, long_break_after=LONG_BREAK_AFTER,
                next_session_type=recommendation, suggested_minutes=DEFAULT_MINUTES[recommendation],
            ),
        )

    async def period(self, period: str, anchor: date | None) -> PeriodMetrics:
        zone, today = await self._calendar()
        validate_dates(anchor, anchor)
        day = today if anchor is None else anchor
        start = end = day
        if period == "weekly":
            start = day - timedelta(days=day.weekday())
            end = start + 6 * DAY
        elif period == "monthly":
            from calendar import monthrange

            start = day.replace(day=1)
            end = day.replace(day=monthrange(day.year, day.month)[1])
        totals, _ = await self._totals(start, end, zone)
        return PeriodMetrics(
            timezone=zone.key, from_date=start, to_date=end,
            days=[DayMetrics(date=day, **row.view().model_dump()) for day, row in totals.items()],
            **aggregate(totals.values()).model_dump(),
        )

    async def by_task(self, filters: TaskFilters) -> Page[TaskMetrics]:
        zone, today = await self._calendar()
        end = today if filters.to_date is None else filters.to_date
        start = end.replace(day=1) if filters.from_date is None else filters.from_date
        validate_dates(start, end)
        if (end - start).days >= 366:
            raise APIError(422, "invalid_input", "Task analytics allow at most 366 days.")
        _, tasks = await self._totals(start, end, zone, task_report=True)
        ordered = sorted(tasks, key=lambda task: (-tasks[task], str(task)))
        items = [TaskMetrics(task_id=task, focus_microseconds=tasks[task], focus_minutes=minutes(tasks[task]))
                 for task in ordered[filters.offset:filters.offset + filters.limit]]
        return Page[TaskMetrics](items=items, limit=filters.limit, offset=filters.offset,
                                 has_more=len(ordered) > filters.offset + filters.limit)
