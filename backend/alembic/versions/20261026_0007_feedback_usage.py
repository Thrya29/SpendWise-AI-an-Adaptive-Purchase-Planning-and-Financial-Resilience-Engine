"""feedback and opt-in usage statistics

Revision ID: 9a4e2b7c1d30
Revises: 6b1f0c9d2e47
Create Date: 2026-10-26 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9a4e2b7c1d30"
down_revision: str | None = "6b1f0c9d2e47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("kind", sa.Enum("comment", "checkin", name="feedbackkind", native_enum=False,
                                  length=24), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=True),
        sa.Column("message", sa.String(length=2000), nullable=True),
        sa.Column("page", sa.String(length=120), nullable=True),
        sa.Column("month", sa.String(length=7), nullable=True),
        sa.Column("answers", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "rating IS NULL OR (rating >= 1 AND rating <= 5)", name=op.f("ck_feedback_rating_range")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_feedback_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
        sa.UniqueConstraint("user_id", "kind", "month", name="uq_feedback_checkin_month"),
    )  # fmt: skip
    op.create_index(op.f("ix_feedback_user_id"), "feedback", ["user_id"], unique=False)
    op.create_table(
        "usage_events",
        sa.Column("subject", sa.String(length=32), nullable=False),
        sa.Column("event", sa.String(length=40), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("value", sa.Integer(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_events")),
    )
    op.create_index(op.f("ix_usage_events_day"), "usage_events", ["day"], unique=False)
    op.create_index(op.f("ix_usage_events_subject"), "usage_events", ["subject"], unique=False)
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("share_usage", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch.add_column(sa.Column("last_active_on", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("last_active_on")
        batch.drop_column("share_usage")
    op.drop_index(op.f("ix_usage_events_subject"), table_name="usage_events")
    op.drop_index(op.f("ix_usage_events_day"), table_name="usage_events")
    op.drop_table("usage_events")
    op.drop_index(op.f("ix_feedback_user_id"), table_name="feedback")
    op.drop_table("feedback")
