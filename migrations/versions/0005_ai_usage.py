"""Add per-account AI usage and recommendation deduplication."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_usage",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("usage_on", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        *[sa.Column(name, sa.Integer(), nullable=False, server_default="0")
          for name in ("request_count", "provider_calls", "reported_tokens", "budgeted_tokens")],
        sa.Column("selections", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "usage_on"),
        sa.CheckConstraint(
            "request_count >= 0 AND provider_calls >= 0 AND reported_tokens >= 0 "
            "AND budgeted_tokens >= reported_tokens", name="nonnegative_usage",
        ),
    )
    op.create_index("ix_ai_usage_usage_on", "ai_usage", ["usage_on"])


def downgrade():
    op.drop_table("ai_usage")
