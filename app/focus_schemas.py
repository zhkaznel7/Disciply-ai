from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.planning_schemas import Input, LocalDate, Pagination

SessionType = Literal["focus", "short_break", "long_break"]
Status = Literal["active", "paused", "completed", "cancelled"]
Duration = Annotated[int, Field(strict=True, ge=1, le=1440)]
DEFAULT_MINUTES: dict[SessionType, int] = {"focus": 25, "short_break": 5, "long_break": 15}
LONG_BREAK_AFTER = 4


class StartSession(Input):
    task_id: UUID | None = None
    session_type: SessionType = "focus"
    planned_minutes: Duration | None = None


class HistoryFilters(Pagination):
    status: Status | None = None
    session_type: SessionType | None = None
    from_date: LocalDate | None = None
    to_date: LocalDate | None = None


class SessionView(BaseModel):
    id: UUID
    task_id: UUID | None
    session_type: SessionType
    status: Status
    started_at: datetime
    ended_at: datetime | None
    created_at: datetime
    updated_at: datetime
    planned_minutes: int
    actual_running_microseconds: int
    actual_focused_microseconds: int
    total_paused_microseconds: int


class Metrics(BaseModel):
    focus_microseconds: int
    focus_minutes: float
    break_microseconds: int
    break_minutes: float
    completed_focus_sessions: int
    average_completed_focus_minutes: float


class DayMetrics(Metrics):
    date: date


class PeriodMetrics(Metrics):
    timezone: str
    from_date: date
    to_date: date
    days: list[DayMetrics]


class Pomodoro(BaseModel):
    completed_focus_since_long_break: int
    long_break_after: int
    next_session_type: SessionType
    suggested_minutes: int


class FocusSummary(BaseModel):
    timezone: str
    date: date
    today: Metrics
    weekly: Metrics
    monthly: Metrics
    pomodoro: Pomodoro


class TaskMetrics(BaseModel):
    task_id: UUID | None
    focus_microseconds: int
    focus_minutes: float


class TaskFilters(Pagination):
    from_date: LocalDate | None = None
    to_date: LocalDate | None = None
