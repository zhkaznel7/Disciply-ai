from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.habit_schemas import Progress
from app.planning_schemas import Input

Action = Literal["small_step", "habit_cue", "focus_block", "goal_step", "reduce_load",
                 "protect_time", "keep_routine", "review_energy"]
Source = Literal["rules", "provider", "cache"]


class CoachRequest(Input):
    include_reflection_mood: Annotated[bool, Field(strict=True)] = False


class PlanRequest(Input):
    available_minutes: Annotated[int, Field(strict=True, ge=15, le=720)] = 120


class Selection(Input):
    actions: Annotated[list[Action], Field(min_length=1, max_length=4)]
    task_refs: Annotated[list[Annotated[int, Field(strict=True, ge=1, le=20)]], Field(max_length=5)]


class Metrics(Input):
    tasks: Progress
    habits: Progress
    focus_minutes: float
    average_discipline_score: float | None
    scored_days: int
    observed_days: int


class Advice(Input):
    code: Action
    text: str


class CoachView(Input):
    date: date
    source: Source
    weekly_facts: Metrics
    discipline_score_today: int | None
    active_goals: int
    average_goal_progress: float | None
    suggestions: list[Advice]


class PlanTask(Input):
    id: UUID
    title: str
    priority: int
    minutes: int
    estimated: bool
    reason: str


class FocusBlock(Input):
    task_id: UUID
    minutes: int
    scheduled_start_at: datetime | None = None


class PlanView(Input):
    date: date
    source: Source
    available_minutes: int
    estimated_workload_minutes: int
    candidate_count: int
    overload: bool
    tasks: list[PlanTask]
    focus_block_minutes: int
    focus_blocks: list[FocusBlock]
    suggestions: list[Advice]


class ReviewView(Input):
    from_date: date
    to_date: date
    source: Source
    current: Metrics
    previous: Metrics
    focus_minutes_change: float | None
    task_completion_change: float | None
    habit_completion_change: float | None
    discipline_score_change: float | None
    achievements: list[str]
    areas_for_improvement: list[Advice]
    priorities: list[Advice]


class StatusView(Input):
    external_enabled: bool
    fallback_available: bool = True


class UsageView(Input):
    date_utc: date
    requests: int
    request_limit: int
    provider_calls: int
    reported_tokens: int
    budgeted_tokens: int
    token_limit: int


class PeriodView(Input):
    from_date: date
    to_date: date
    timezone: str
    metrics: Metrics


class InsightsView(Input):
    weekly_facts: Metrics
    suggestions: list[Advice]
