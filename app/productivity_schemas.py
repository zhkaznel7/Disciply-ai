from datetime import date as Date
from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.focus_schemas import Metrics
from app.habit_schemas import Progress
from app.planning_schemas import Input, LocalDate, valid_text

Notes = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
    AfterValidator(valid_text),
]


class DateQuery(Input):
    date: LocalDate | None = None


class RangeQuery(Input):
    from_date: LocalDate
    to_date: LocalDate


class ReflectionWrite(Input):
    notes: Notes
    mood: Annotated[int, Field(strict=True, ge=1, le=5)] | None = None


class ReflectionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    date: Date = Field(validation_alias="reflected_on")
    notes: str
    mood: int | None
    created_at: datetime


class ScoreComponent(BaseModel):
    weight: int
    applicable: bool
    completion_percentage: float


class DisciplineScore(BaseModel):
    version: str = "v1"
    value: int | None
    focus_target_minutes: int
    tasks: ScoreComponent
    habits: ScoreComponent
    focus: ScoreComponent


class ProductivityDay(BaseModel):
    date: Date
    timezone: str
    tasks: Progress
    habits: Progress
    focus: Metrics
    discipline_score: DisciplineScore
    has_evening_reflection: bool


class ProductivityRange(BaseModel):
    timezone: str
    from_date: Date
    to_date: Date
    days: list[ProductivityDay]
