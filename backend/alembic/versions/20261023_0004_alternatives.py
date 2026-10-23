"""alternatives

Revision ID: fac241682015
Revises: 8d33153536f6
Create Date: 2026-10-23 16:46:46.341263
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fac241682015"
down_revision: str | None = "8d33153536f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:

    op.add_column("planned_items", sa.Column("alternative_group", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_planned_items_alternative_group"),
        "planned_items",
        ["alternative_group"],
        unique=False,
    )


def downgrade() -> None:

    op.drop_index(op.f("ix_planned_items_alternative_group"), table_name="planned_items")
    op.drop_column("planned_items", "alternative_group")
