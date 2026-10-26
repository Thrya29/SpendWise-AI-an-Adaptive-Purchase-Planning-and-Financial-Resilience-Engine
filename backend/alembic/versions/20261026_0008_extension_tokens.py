"""browser extension keys

Revision ID: c3d8e1f5a920
Revises: 9a4e2b7c1d30
Create Date: 2026-10-26 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d8e1f5a920"
down_revision: str | None = "9a4e2b7c1d30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "extension_tokens",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("hint", sa.String(length=8), nullable=False),
        sa.Column("label", sa.String(length=60), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_extension_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extension_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_extension_tokens_token_hash")),
    )  # fmt: skip
    op.create_index(
        op.f("ix_extension_tokens_user_id"), "extension_tokens", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_extension_tokens_user_id"), table_name="extension_tokens")
    op.drop_table("extension_tokens")
