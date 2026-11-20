"""Add habit schedules, completion counts, and update timestamps."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("habits", "habit_logs"):
        op.add_column(table, sa.Column("updated_at", sa.DateTime(timezone=True)))
        op.execute(sa.text(f"UPDATE {table} SET updated_at = created_at"))
        op.alter_column(table, "updated_at", nullable=False, server_default=sa.func.now())

    op.add_column("habits", sa.Column("description", sa.String(4000)))
    op.add_column("habits", sa.Column("frequency", sa.String(8), nullable=False, server_default="daily"))
    op.add_column("habits", sa.Column("weekday_mask", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("habits", sa.Column("weekly_target", sa.Integer()))
    op.add_column("habits", sa.Column("target_count", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("habits", sa.Column("preferred_time", sa.Time()))
    op.add_column("habits", sa.Column("starts_on", sa.Date()))
    op.execute(sa.text("""
        UPDATE habits SET starts_on = LEAST(
            (created_at AT TIME ZONE 'UTC')::date,
            (SELECT min(logged_on) FROM habit_logs
             WHERE habit_logs.user_id = habits.user_id AND habit_logs.habit_id = habits.id)
        )
    """))
    op.alter_column("habits", "starts_on", nullable=False,
                    server_default=sa.text("(CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date"))
    op.create_check_constraint("target_count", "habits", "target_count BETWEEN 1 AND 1000000")
    op.create_check_constraint(
        "schedule", "habits",
        "(frequency = 'daily' AND weekday_mask = 0 AND weekly_target IS NULL) OR "
        "(frequency = 'weekdays' AND weekday_mask BETWEEN 1 AND 127 AND weekly_target IS NULL) OR "
        "(frequency = 'weekly' AND weekday_mask = 0 AND weekly_target IS NOT NULL "
        "AND weekly_target BETWEEN 1 AND 7)",
    )
    op.add_column("habit_logs", sa.Column("count", sa.Integer(), nullable=False, server_default="1"))
    op.create_check_constraint("count", "habit_logs", "count BETWEEN 1 AND 1000000")


def downgrade():
    op.drop_constraint(op.f("ck_habit_logs_count"), "habit_logs", type_="check")
    op.drop_column("habit_logs", "count")
    op.drop_column("habit_logs", "updated_at")
    for name in ("schedule", "target_count"):
        op.drop_constraint(op.f(f"ck_habits_{name}"), "habits", type_="check")
    for name in ("starts_on", "preferred_time", "target_count", "weekly_target",
                 "weekday_mask", "frequency", "description", "updated_at"):
        op.drop_column("habits", name)
