from datetime import date, datetime, time
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = sa.MetaData(naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })


class Record:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class Owned:
    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))


class User(Record, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(sa.String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(sa.String(255))


class UserSettings(Record, Owned, Base):
    __tablename__ = "user_settings"
    __table_args__ = (
        sa.UniqueConstraint("user_id"),
        sa.CheckConstraint("week_starts_on BETWEEN 0 AND 6", name="week_start"),
    )
    timezone: Mapped[str] = mapped_column(sa.String(64), server_default="UTC")
    week_starts_on: Mapped[int] = mapped_column(server_default="0")


class PlanningRecord:
    description: Mapped[str | None] = mapped_column(sa.String(4000))
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.clock_timestamp()
    )


class Goal(PlanningRecord, Record, Owned, Base):
    __tablename__ = "goals"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "id"),
        sa.CheckConstraint("priority BETWEEN 0 AND 3", name="priority"),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name="progress"),
        sa.CheckConstraint("(progress = 100) = (completed_at IS NOT NULL)", name="completion"),
    )
    title: Mapped[str] = mapped_column(sa.String(200))
    target_on: Mapped[date | None]
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    priority: Mapped[int] = mapped_column(server_default="0")
    progress: Mapped[int] = mapped_column(server_default="0")

    @property
    def status(self) -> str:
        return "completed" if self.completed_at is not None else "active"


class Project(PlanningRecord, Record, Owned, Base):
    __tablename__ = "projects"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "id"),
        sa.ForeignKeyConstraint(["user_id", "goal_id"], ["goals.user_id", "goals.id"]),
        sa.Index(None, "user_id", "goal_id"),
        sa.CheckConstraint("target_on >= starts_on", name="date_order"),
    )
    goal_id: Mapped[UUID | None]
    title: Mapped[str] = mapped_column(sa.String(200))
    archived_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    starts_on: Mapped[date | None]
    target_on: Mapped[date | None]

    @property
    def status(self) -> str:
        return "archived" if self.archived_at is not None else "active"


class Task(PlanningRecord, Record, Owned, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "id"),
        sa.ForeignKeyConstraint(["user_id", "project_id"], ["projects.user_id", "projects.id"]),
        sa.CheckConstraint("priority BETWEEN 0 AND 3", name="priority"),
        sa.ForeignKeyConstraint(["user_id", "goal_id"], ["goals.user_id", "goals.id"]),
        sa.CheckConstraint(
            "scheduled_start_at IS NULL OR scheduled_on IS NOT NULL", name="scheduled_date"
        ),
        sa.CheckConstraint(
            "scheduled_end_at IS NULL OR "
            "(scheduled_start_at IS NOT NULL AND scheduled_end_at > scheduled_start_at)",
            name="scheduled_time_order",
        ),
        sa.Index(None, "user_id", "goal_id"),
        sa.Index(None, "user_id", "scheduled_on"),
        sa.Index(None, "user_id", "project_id"),
    )
    project_id: Mapped[UUID | None]
    goal_id: Mapped[UUID | None]
    title: Mapped[str] = mapped_column(sa.String(200))
    scheduled_on: Mapped[date | None]
    scheduled_start_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    scheduled_end_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    priority: Mapped[int] = mapped_column(server_default="0")

    @property
    def status(self) -> str:
        return "completed" if self.completed_at is not None else "open"


class Habit(PlanningRecord, Record, Owned, Base):
    __tablename__ = "habits"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "id"),
        sa.CheckConstraint("target_count BETWEEN 1 AND 1000000", name="target_count"),
        sa.CheckConstraint(
            "(frequency = 'daily' AND weekday_mask = 0 AND weekly_target IS NULL) OR "
            "(frequency = 'weekdays' AND weekday_mask BETWEEN 1 AND 127 AND weekly_target IS NULL) OR "
            "(frequency = 'weekly' AND weekday_mask = 0 AND weekly_target IS NOT NULL "
            "AND weekly_target BETWEEN 1 AND 7)", name="schedule",
        ),
    )
    title: Mapped[str] = mapped_column(sa.String(200))
    frequency: Mapped[str] = mapped_column(sa.String(8), server_default="daily")
    weekday_mask: Mapped[int] = mapped_column(server_default="0")
    weekly_target: Mapped[int | None]
    target_count: Mapped[int] = mapped_column(server_default="1")
    preferred_time: Mapped[time | None]
    starts_on: Mapped[date] = mapped_column(
        server_default=sa.text("(CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date")
    )
    archived_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    @property
    def status(self) -> str:
        return "archived" if self.archived_at is not None else "active"

    @property
    def weekdays(self) -> list[int]:
        return [day for day in range(7) if self.weekday_mask & (1 << day)]


class HabitLog(Record, Owned, Base):
    __tablename__ = "habit_logs"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id", "habit_id"], ["habits.user_id", "habits.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("user_id", "habit_id", "logged_on"),
        sa.CheckConstraint("count BETWEEN 1 AND 1000000", name="count"),
    )
    habit_id: Mapped[UUID]
    logged_on: Mapped[date]
    count: Mapped[int] = mapped_column(server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.clock_timestamp()
    )


class FocusSession(Record, Owned, Base):
    __tablename__ = "focus_sessions"
    __table_args__ = (
        sa.CheckConstraint("ended_at IS NULL OR ended_at > started_at", name="time_order"),
        sa.CheckConstraint("session_type IN ('focus', 'short_break', 'long_break')", name="type"),
        sa.CheckConstraint("planned_minutes BETWEEN 1 AND 1440", name="planned_duration"),
        sa.CheckConstraint(
            "(status IN ('active', 'paused') AND ended_at IS NULL) OR "
            "(status IN ('completed', 'cancelled') AND ended_at IS NOT NULL)", name="state",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "task_id"], ["tasks.user_id", "tasks.id"], ondelete="SET NULL (task_id)"
        ),
        sa.Index(None, "user_id", "started_at"),
        sa.Index(None, "user_id", "task_id", postgresql_where=sa.text("task_id IS NOT NULL")),
        sa.Index(None, "user_id", "ended_at", postgresql_where=sa.text("status = 'completed'")),
        sa.Index("uq_focus_sessions_unfinished", "user_id", unique=True,
                 postgresql_where=sa.text("ended_at IS NULL")),
    )
    task_id: Mapped[UUID | None]
    session_type: Mapped[str] = mapped_column(sa.String(11), server_default="focus")
    status: Mapped[str] = mapped_column(sa.String(9), server_default="active")
    planned_minutes: Mapped[int] = mapped_column(server_default="25")
    started_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.clock_timestamp()
    )


class FocusInterval(Record, Base):
    __tablename__ = "focus_intervals"
    __table_args__ = (
        sa.CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="time_order"),
        sa.Index(None, "session_id"),
        sa.Index("uq_focus_intervals_open", "session_id", unique=True,
                 postgresql_where=sa.text("ended_at IS NULL")),
    )
    session_id: Mapped[UUID] = mapped_column(sa.ForeignKey("focus_sessions.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class DailyStatistic(Record, Owned, Base):
    __tablename__ = "daily_statistics"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "statistic_on"),
        sa.CheckConstraint("tasks_completed >= 0 AND habits_completed >= 0 AND focus_seconds >= 0",
                           name="nonnegative_totals"),
        sa.CheckConstraint("discipline_score BETWEEN 0 AND 100", name="score_range"),
    )
    statistic_on: Mapped[date]
    tasks_completed: Mapped[int] = mapped_column(server_default="0")
    habits_completed: Mapped[int] = mapped_column(server_default="0")
    focus_seconds: Mapped[int] = mapped_column(server_default="0")
    discipline_score: Mapped[int | None]


class EveningReflection(Record, Owned, Base):
    __tablename__ = "evening_reflections"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "reflected_on"),
        sa.CheckConstraint("mood BETWEEN 1 AND 5", name="mood_range"),
    )
    reflected_on: Mapped[date]
    notes: Mapped[str] = mapped_column(sa.Text)
    mood: Mapped[int | None]


class RefreshSession(Record, Owned, Base):
    __tablename__ = "refresh_sessions"
    __table_args__ = (
        sa.CheckConstraint("expires_at > created_at", name="expiry_order"),
        sa.Index(None, "user_id"),
        sa.Index(None, "expires_at"),
    )
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class RefreshCredential(Record, Base):
    __tablename__ = "refresh_credentials"
    __table_args__ = (
        sa.Index("uq_refresh_credentials_active", "session_id", unique=True,
                 postgresql_where=sa.text("consumed_at IS NULL")),
        sa.Index(None, "session_id"),
    )
    session_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("refresh_sessions.id", ondelete="CASCADE")
    )
    digest: Mapped[bytes] = mapped_column(sa.LargeBinary(32), unique=True)
    consumed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class AIUsage(Record, Owned, Base):
    __tablename__ = "ai_usage"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "usage_on"),
        sa.CheckConstraint(
            "request_count >= 0 AND provider_calls >= 0 AND reported_tokens >= 0 "
            "AND budgeted_tokens >= reported_tokens", name="nonnegative_usage",
        ),
        sa.Index(None, "usage_on"),
    )
    usage_on: Mapped[date]
    request_count: Mapped[int] = mapped_column(server_default="0")
    provider_calls: Mapped[int] = mapped_column(server_default="0")
    reported_tokens: Mapped[int] = mapped_column(server_default="0")
    budgeted_tokens: Mapped[int] = mapped_column(server_default="0")
    selections: Mapped[dict] = mapped_column(JSONB, server_default=sa.text("'{}'::jsonb"))
