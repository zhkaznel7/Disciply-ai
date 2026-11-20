"""Add focus lifecycle state and running intervals."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

timestamp = sa.DateTime(timezone=True)


def upgrade():
    # Exclude concurrent legacy writes between the preflight and index creation.
    op.execute("LOCK TABLE focus_sessions IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT user_id FROM focus_sessions WHERE ended_at IS NULL
                GROUP BY user_id HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION 'Multiple unfinished legacy focus sessions for an owner. Reconcile their end timestamps before migrating.';
            END IF;
        END
        $$;
    """)
    op.create_unique_constraint("uq_tasks_user_id_id", "tasks", ["user_id", "id"])
    op.add_column("focus_sessions", sa.Column("task_id", sa.Uuid()))
    op.add_column("focus_sessions", sa.Column("session_type", sa.String(11),
                                             nullable=False, server_default="focus"))
    op.add_column("focus_sessions", sa.Column("status", sa.String(9),
                                             nullable=False, server_default="active"))
    op.add_column("focus_sessions", sa.Column("planned_minutes", sa.Integer(),
                                             nullable=False, server_default="25"))
    op.add_column("focus_sessions", sa.Column("updated_at", timestamp))
    op.execute("""
        UPDATE focus_sessions SET
            status = CASE WHEN ended_at IS NULL THEN 'active' ELSE 'completed' END,
            updated_at = GREATEST(created_at, ended_at)
    """)
    op.alter_column("focus_sessions", "updated_at", nullable=False, server_default=sa.func.now())
    op.create_check_constraint("type", "focus_sessions",
                               "session_type IN ('focus', 'short_break', 'long_break')")
    op.create_check_constraint("planned_duration", "focus_sessions", "planned_minutes BETWEEN 1 AND 1440")
    op.create_check_constraint(
        "state", "focus_sessions",
        "(status IN ('active', 'paused') AND ended_at IS NULL) OR "
        "(status IN ('completed', 'cancelled') AND ended_at IS NOT NULL)",
    )
    op.create_foreign_key(
        "fk_focus_sessions_user_id_task_id_tasks", "focus_sessions", "tasks",
        ["user_id", "task_id"], ["user_id", "id"], ondelete="SET NULL (task_id)",
    )
    op.create_index("ix_focus_sessions_user_id_task_id", "focus_sessions", ["user_id", "task_id"],
                    postgresql_where=sa.text("task_id IS NOT NULL"))
    op.create_index("ix_focus_sessions_user_id_ended_at", "focus_sessions", ["user_id", "ended_at"],
                    postgresql_where=sa.text("status = 'completed'"))
    op.create_index("uq_focus_sessions_unfinished", "focus_sessions", ["user_id"], unique=True,
                    postgresql_where=sa.text("ended_at IS NULL"))
    op.create_table(
        "focus_intervals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", timestamp, nullable=False),
        sa.Column("ended_at", timestamp),
        sa.ForeignKeyConstraint(["session_id"], ["focus_sessions.id"], ondelete="CASCADE"),
        sa.CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="time_order"),
    )
    op.create_index("ix_focus_intervals_session_id", "focus_intervals", ["session_id"])
    op.create_index("uq_focus_intervals_open", "focus_intervals", ["session_id"], unique=True,
                    postgresql_where=sa.text("ended_at IS NULL"))
    op.execute("""
        INSERT INTO focus_intervals (id, session_id, created_at, started_at, ended_at)
        SELECT id, id, created_at, started_at, ended_at FROM focus_sessions
    """)


def downgrade():
    op.drop_table("focus_intervals")
    for name in ("uq_focus_sessions_unfinished", "ix_focus_sessions_user_id_ended_at",
                 "ix_focus_sessions_user_id_task_id"):
        op.drop_index(name, table_name="focus_sessions")
    op.drop_constraint("fk_focus_sessions_user_id_task_id_tasks", "focus_sessions", type_="foreignkey")
    for name in ("state", "planned_duration", "type"):
        op.drop_constraint(op.f(f"ck_focus_sessions_{name}"), "focus_sessions", type_="check")
    for name in ("updated_at", "planned_minutes", "status", "session_type", "task_id"):
        op.drop_column("focus_sessions", name)
    op.drop_constraint("uq_tasks_user_id_id", "tasks", type_="unique")
