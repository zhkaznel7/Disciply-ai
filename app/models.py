from datetime import date, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
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


class Habit(Record, Owned, Base):
    __tablename__ = "habits"
    __table_args__ = (sa.UniqueConstraint("user_id", "id"),)
    title: Mapped[str] = mapped_column(sa.String(200))
    archived_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class HabitLog(Record, Owned, Base):
    __tablename__ = "habit_logs"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id", "habit_id"], ["habits.user_id", "habits.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("user_id", "habit_id", "logged_on"),
    )
    habit_id: Mapped[UUID]
    logged_on: Mapped[date]


class FocusSession(Record, Owned, Base):
    __tablename__ = "focus_sessions"
    __table_args__ = (
        sa.CheckConstraint("ended_at IS NULL OR ended_at > started_at", name="time_order"),
        sa.Index(None, "user_id", "started_at"),
    )
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
