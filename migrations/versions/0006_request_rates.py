"""Add shared request throttling buckets."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "request_rates",
        sa.Column("window", sa.BigInteger(), primary_key=True),
        sa.Column("bucket", sa.String(12), primary_key=True),
        sa.Column("fingerprint", sa.LargeBinary(32), primary_key=True),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.CheckConstraint("hits > 0", name="positive_hits"),
    )


def downgrade():
    op.drop_table("request_rates")
