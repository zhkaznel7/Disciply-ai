"""Extend existing goals, projects, and tasks for planning."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLES = ("goals", "projects", "tasks")


def upgrade():
    for table in TABLES:
        op.add_column(table, sa.Column("description", sa.String(4000)))
        op.add_column(table, sa.Column("updated_at", sa.DateTime(timezone=True)))
        op.execute(sa.text(f"UPDATE {table} SET updated_at = created_at"))
        op.alter_column(table, "updated_at", nullable=False, server_default=sa.func.now())

    op.add_column("goals", sa.Column("priority", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("goals", sa.Column("progress", sa.Integer(), nullable=False, server_default="0"))
    op.execute(sa.text("UPDATE goals SET progress = 100 WHERE completed_at IS NOT NULL"))
    op.create_check_constraint("priority", "goals", "priority BETWEEN 0 AND 3")
    op.create_check_constraint("progress", "goals", "progress BETWEEN 0 AND 100")
    op.create_check_constraint("completion", "goals", "(progress = 100) = (completed_at IS NOT NULL)")

    for column in ("starts_on", "target_on"):
        op.add_column("projects", sa.Column(column, sa.Date()))
    op.create_check_constraint("date_order", "projects", "target_on >= starts_on")

    op.add_column("tasks", sa.Column("goal_id", sa.Uuid()))
    for column in ("scheduled_start_at", "scheduled_end_at"):
        op.add_column("tasks", sa.Column(column, sa.DateTime(timezone=True)))
    op.create_foreign_key(
        "fk_tasks_user_id_goal_id_goals", "tasks", "goals", ["user_id", "goal_id"], ["user_id", "id"]
    )
    op.create_index("ix_tasks_user_id_goal_id", "tasks", ["user_id", "goal_id"])
    op.create_check_constraint(
        "scheduled_date", "tasks", "scheduled_start_at IS NULL OR scheduled_on IS NOT NULL"
    )
    op.create_check_constraint(
        "scheduled_time_order", "tasks",
        "scheduled_end_at IS NULL OR "
        "(scheduled_start_at IS NOT NULL AND scheduled_end_at > scheduled_start_at)",
    )


def downgrade():
    op.drop_constraint(op.f("ck_tasks_scheduled_time_order"), "tasks", type_="check")
    op.drop_constraint(op.f("ck_tasks_scheduled_date"), "tasks", type_="check")
    op.drop_index("ix_tasks_user_id_goal_id", table_name="tasks")
    op.drop_constraint("fk_tasks_user_id_goal_id_goals", "tasks", type_="foreignkey")
    for column in ("scheduled_end_at", "scheduled_start_at", "goal_id"):
        op.drop_column("tasks", column)

    op.drop_constraint(op.f("ck_projects_date_order"), "projects", type_="check")
    op.drop_column("projects", "target_on")
    op.drop_column("projects", "starts_on")

    for name in ("completion", "progress", "priority"):
        op.drop_constraint(op.f(f"ck_goals_{name}"), "goals", type_="check")
    op.drop_column("goals", "progress")
    op.drop_column("goals", "priority")
    for table in TABLES:
        op.drop_column(table, "updated_at")
        op.drop_column(table, "description")
