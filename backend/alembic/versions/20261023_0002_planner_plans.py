"""planner plans

Revision ID: 4b2454350252
Revises: 1c057761cb4d
Create Date: 2026-10-23 14:54:37.120409
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4b2454350252"
down_revision: str | None = "1c057761cb4d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:

    op.create_table(
        "plans",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "draft", "applied", "discarded", name="planstatus", native_enum=False, length=24
            ),
            nullable=False,
        ),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("horizon_months", sa.SmallInteger(), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_plans_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plans")),
    )
    op.create_index(op.f("ix_plans_created_at"), "plans", ["created_at"], unique=False)
    op.create_index(op.f("ix_plans_user_id"), "plans", ["user_id"], unique=False)


def downgrade() -> None:

    op.drop_index(op.f("ix_plans_user_id"), table_name="plans")
    op.drop_index(op.f("ix_plans_created_at"), table_name="plans")
    op.drop_table("plans")
