import re
from datetime import UTC, date, datetime
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import AfterValidator, AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, model_validator


def iso_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Use YYYY-MM-DD")
    return value


def timestamp_string(value):
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("Use an ISO 8601 timestamp with a UTC offset")
    return value


def valid_text(value: str) -> str:
    if "\x00" in value:
        raise ValueError("Text cannot contain a null character")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("Text must contain valid Unicode") from None
    return value


def representable_timestamp(value: datetime) -> datetime:
    try:
        return value.astimezone(UTC)
    except OverflowError:
        raise ValueError("Timestamp is outside the supported UTC range") from None


LocalDate = Annotated[date, BeforeValidator(iso_date)]
Timestamp = Annotated[AwareDatetime, BeforeValidator(timestamp_string), AfterValidator(representable_timestamp)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200), AfterValidator(valid_text)]
Description = Annotated[str, StringConstraints(max_length=4000), AfterValidator(valid_text)]
Priority = Annotated[int, Field(ge=0, le=3)]
BodyPriority = Annotated[int, Field(strict=True, ge=0, le=3)]
Progress = Annotated[int, Field(strict=True, ge=0, le=100)]
GoalStatus = Literal["active", "completed"]
ProjectStatus = Literal["active", "archived"]
TaskStatus = Literal["open", "completed"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class CreateRecord(Input):
    title: Title
    description: Description | None = None


class UpdateRecord(Input):
    title: Title | None = None
    description: Description | None = None

    @model_validator(mode="after")
    def validate_update(self):
        values = self.model_dump(exclude_unset=True)
        if not values or any(
            name in values and values[name] is None
            for name in ("title", "status", "priority", "progress")
        ):
            raise ValueError("Send at least one change and use non-null values for required fields")
        return self


class GoalCreate(CreateRecord):
    target_on: LocalDate | None = None
    priority: BodyPriority = 0
    progress: Progress | None = None
    status: GoalStatus | None = None


class GoalUpdate(UpdateRecord):
    target_on: LocalDate | None = None
    priority: BodyPriority | None = None
    progress: Progress | None = None
    status: GoalStatus | None = None


class ProjectCreate(CreateRecord):
    goal_id: UUID | None = None
    starts_on: LocalDate | None = None
    target_on: LocalDate | None = None
    status: ProjectStatus = "active"


class ProjectUpdate(UpdateRecord):
    goal_id: UUID | None = None
    starts_on: LocalDate | None = None
    target_on: LocalDate | None = None
    status: ProjectStatus | None = None


class TaskFields(Input):
    project_id: UUID | None = None
    goal_id: UUID | None = None
    scheduled_on: LocalDate | None = None
    scheduled_start_at: Timestamp | None = None
    scheduled_end_at: Timestamp | None = None
    due_at: Timestamp | None = None


class TaskCreate(CreateRecord, TaskFields):
    priority: BodyPriority = 0
    status: TaskStatus = "open"


class TaskUpdate(UpdateRecord, TaskFields):
    priority: BodyPriority | None = None
    status: TaskStatus | None = None


class RecordView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class GoalView(RecordView):
    target_on: date | None
    priority: Priority
    progress: Progress
    status: GoalStatus
    completed_at: datetime | None


class ProjectView(RecordView):
    goal_id: UUID | None
    starts_on: date | None
    target_on: date | None
    status: ProjectStatus
    archived_at: datetime | None


class TaskView(RecordView):
    project_id: UUID | None
    goal_id: UUID | None
    scheduled_on: date | None
    scheduled_start_at: datetime | None
    scheduled_end_at: datetime | None
    due_at: datetime | None
    completed_at: datetime | None
    priority: Priority
    status: TaskStatus


class Pagination(Input):
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0, le=100_000)


class GoalFilters(Pagination):
    status: GoalStatus | None = None
    target_on: LocalDate | None = None


class ProjectFilters(Pagination):
    status: ProjectStatus | None = None


class TaskFilters(Pagination):
    status: TaskStatus | None = None
    priority: Priority | None = None
    project_id: UUID | None = None
    goal_id: UUID | None = None
    scheduled_on: LocalDate | None = None
    overdue: bool | None = None


View = TypeVar("View")


class PageInfo(BaseModel):
    limit: int
    offset: int
    has_more: bool


class Page(PageInfo, Generic[View]):
    items: list[View]


class PlannerDay(BaseModel):
    date: date
    tasks: list[TaskView]


class DailyPlan(PlannerDay, PageInfo):
    timezone: str


class WeeklyPlan(PageInfo):
    start_date: date
    timezone: str
    days: list[PlannerDay]
