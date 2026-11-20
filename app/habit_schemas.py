import re
from datetime import date as Date
from datetime import datetime, time
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from app.planning_schemas import Description, Input, LocalDate, Pagination, RecordView, Title

Frequency = Literal["daily", "weekdays", "weekly"]
HabitStatus = Literal["active", "archived"]
Count = Annotated[int, Field(strict=True, ge=1, le=1_000_000)]
Weekday = Annotated[int, Field(strict=True, ge=0, le=6)]
Weekdays = Annotated[list[Weekday], Field(max_length=7)]
WeeklyTarget = Annotated[int, Field(strict=True, ge=1, le=7)]


def local_time(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{2}:[0-9]{2}(:[0-9]{2})?", value):
        raise ValueError("Use HH:MM or HH:MM:SS in local time")
    return value


PreferredTime = Annotated[time, BeforeValidator(local_time)]


class HabitFields(Input):
    description: Description | None = None
    weekdays: Weekdays = Field(default_factory=list)
    weekly_target: WeeklyTarget | None = None
    preferred_time: PreferredTime | None = None


class HabitCreate(HabitFields):
    title: Title
    frequency: Frequency = "daily"
    target_count: Count = 1
    starts_on: LocalDate | None = None


class HabitUpdate(HabitFields):
    title: Title | None = None
    frequency: Frequency | None = None
    target_count: Count | None = None
    starts_on: LocalDate | None = None
    status: HabitStatus | None = None

    @model_validator(mode="after")
    def validate_patch(self):
        if not self.model_fields_set or any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in ("title", "frequency", "target_count", "starts_on", "status")
        ):
            raise ValueError("Send at least one change and use non-null values for required fields")
        return self


class HabitView(RecordView):
    frequency: Frequency
    target_count: Count
    weekdays: list[int]
    weekly_target: int | None
    preferred_time: time | None
    starts_on: Date
    status: HabitStatus
    archived_at: datetime | None


class HabitFilters(Pagination):
    status: HabitStatus | None = None


class LogCreate(Input):
    date: LocalDate | None = None
    count: Count = 1


class LogUpdate(Input):
    count: Count


class LogFilters(Pagination):
    from_date: LocalDate | None = None
    to_date: LocalDate | None = None


class LogView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    habit_id: UUID
    date: Date = Field(validation_alias="logged_on")
    count: int
    created_at: datetime
    updated_at: datetime


class Progress(BaseModel):
    completed: int
    target: int
    completion_percentage: float


class DayStatus(BaseModel):
    habit: HabitView
    count: int
    scheduled: bool
    completed: bool


class PeriodHabit(BaseModel):
    habit: HabitView
    progress: Progress


class HabitStats(BaseModel):
    habit: HabitView
    timezone: str
    date: Date
    streak_unit: Literal["days", "weeks"]
    current_streak: int
    longest_streak: int
    last_completed_date: Date | None
    completion_percentage: float
    weekly: Progress
    monthly: Progress


class Summary(BaseModel):
    timezone: str
    date: Date
    total_active_habits: int
    completed_habits_today: int
    today: Progress
    weekly: Progress
    monthly: Progress
