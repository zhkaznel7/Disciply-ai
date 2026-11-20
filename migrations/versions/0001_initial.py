"""Create Phase 1 tables.

Revision ID: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

timestamp = sa.DateTime(timezone=True)


def record(table):
    return (
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", timestamp, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
    )


def owner(table):
    return (
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=f"fk_{table}_user_id_users",
                                ondelete="CASCADE"),
    )


def unique(table, *columns):
    return sa.UniqueConstraint(*columns, name=f"uq_{table}_{'_'.join(columns)}")


def check(table, name, expression):
    return sa.CheckConstraint(expression, name=op.f(f"ck_{table}_{name}"))


def owned_link(table, column, parent, *, cascade=False):
    return sa.ForeignKeyConstraint(
        ["user_id", column], [f"{parent}.user_id", f"{parent}.id"],
        name=f"fk_{table}_user_id_{column}_{parent}", ondelete="CASCADE" if cascade else None,
    )


def upgrade():
    op.create_table(
        "users", *record("users"),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        unique('users', 'email'),
    )
    op.create_table(
        "user_settings", *record("user_settings"), *owner("user_settings"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default='UTC'),
        sa.Column("week_starts_on", sa.Integer(), nullable=False, server_default='0'),
        unique('user_settings', 'user_id'),
        check('user_settings', 'week_start', 'week_starts_on BETWEEN 0 AND 6'),
    )
    op.create_table(
        "goals", *record("goals"), *owner("goals"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("target_on", sa.Date(), nullable=True),
        sa.Column("completed_at", timestamp, nullable=True),
        unique('goals', 'user_id', 'id'),
    )
    op.create_table(
        "projects", *record("projects"), *owner("projects"),
        sa.Column("goal_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("archived_at", timestamp, nullable=True),
        unique('projects', 'user_id', 'id'),
        owned_link('projects', 'goal_id', 'goals'),
    )
    op.create_index("ix_projects_user_id_goal_id", "projects", ["user_id","goal_id"])
    op.create_table(
        "tasks", *record("tasks"), *owner("tasks"),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("scheduled_on", sa.Date(), nullable=True),
        sa.Column("due_at", timestamp, nullable=True),
        sa.Column("completed_at", timestamp, nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default='0'),
        owned_link('tasks', 'project_id', 'projects'),
        check('tasks', 'priority', 'priority BETWEEN 0 AND 3'),
    )
    op.create_index("ix_tasks_user_id_scheduled_on", "tasks", ["user_id","scheduled_on"])
    op.create_index("ix_tasks_user_id_project_id", "tasks", ["user_id","project_id"])
    op.create_table(
        "habits", *record("habits"), *owner("habits"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("archived_at", timestamp, nullable=True),
        unique('habits', 'user_id', 'id'),
    )
    op.create_table(
        "habit_logs", *record("habit_logs"), *owner("habit_logs"),
        sa.Column("habit_id", sa.Uuid(), nullable=False),
        sa.Column("logged_on", sa.Date(), nullable=False),
        owned_link('habit_logs', 'habit_id', 'habits', cascade=True),
        unique('habit_logs', 'user_id', 'habit_id', 'logged_on'),
    )
    op.create_table(
        "focus_sessions", *record("focus_sessions"), *owner("focus_sessions"),
        sa.Column("started_at", timestamp, nullable=False),
        sa.Column("ended_at", timestamp, nullable=True),
        check('focus_sessions', 'time_order', 'ended_at IS NULL OR ended_at > started_at'),
    )
    op.create_index("ix_focus_sessions_user_id_started_at", "focus_sessions", ["user_id","started_at"])
    op.create_table(
        "daily_statistics", *record("daily_statistics"), *owner("daily_statistics"),
        sa.Column("statistic_on", sa.Date(), nullable=False),
        sa.Column("tasks_completed", sa.Integer(), nullable=False, server_default='0'),
        sa.Column("habits_completed", sa.Integer(), nullable=False, server_default='0'),
        sa.Column("focus_seconds", sa.Integer(), nullable=False, server_default='0'),
        sa.Column("discipline_score", sa.Integer(), nullable=True),
        unique('daily_statistics', 'user_id', 'statistic_on'),
        check('daily_statistics', 'nonnegative_totals',
              'tasks_completed >= 0 AND habits_completed >= 0 AND focus_seconds >= 0'),
        check('daily_statistics', 'score_range', 'discipline_score BETWEEN 0 AND 100'),
    )
    op.create_table(
        "evening_reflections", *record("evening_reflections"), *owner("evening_reflections"),
        sa.Column("reflected_on", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("mood", sa.Integer(), nullable=True),
        unique('evening_reflections', 'user_id', 'reflected_on'),
        check('evening_reflections', 'mood_range', 'mood BETWEEN 1 AND 5'),
    )
    op.create_table(
        "refresh_sessions", *record("refresh_sessions"), *owner("refresh_sessions"),
        sa.Column("expires_at", timestamp, nullable=False),
        sa.Column("revoked_at", timestamp, nullable=True),
        check('refresh_sessions', 'expiry_order', 'expires_at > created_at'),
    )
    op.create_index("ix_refresh_sessions_user_id", "refresh_sessions", ["user_id"])
    op.create_index("ix_refresh_sessions_expires_at", "refresh_sessions", ["expires_at"])
    op.create_table(
        "refresh_credentials", *record("refresh_credentials"),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("digest", sa.LargeBinary(32), nullable=False),
        sa.Column("consumed_at", timestamp, nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['refresh_sessions.id'],
                                name='fk_refresh_credentials_session_id_refresh_sessions',
                                ondelete='CASCADE'),
        unique('refresh_credentials', 'digest'),
    )
    op.create_index("ix_refresh_credentials_session_id", "refresh_credentials", ["session_id"])
    op.create_index(
        "uq_refresh_credentials_active", "refresh_credentials", ["session_id"],
        unique=True, postgresql_where=sa.text("consumed_at IS NULL"),
    )


def downgrade():
    op.drop_table("refresh_credentials")
    op.drop_table("refresh_sessions")
    op.drop_table("evening_reflections")
    op.drop_table("daily_statistics")
    op.drop_table("focus_sessions")
    op.drop_table("habit_logs")
    op.drop_table("habits")
    op.drop_table("tasks")
    op.drop_table("projects")
    op.drop_table("goals")
    op.drop_table("user_settings")
    op.drop_table("users")
