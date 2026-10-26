"""notifications

Revision ID: 6b1f0c9d2e47
Revises: 4330028a31f8
Create Date: 2026-10-26 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6b1f0c9d2e47"
down_revision: str | None = "4330028a31f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # batch mode: SQLite cannot add a unique constraint to an existing table otherwise.
    with op.batch_alter_table("alerts") as batch:
        batch.add_column(sa.Column("dedupe_key", sa.String(length=160), nullable=True))
        batch.add_column(sa.Column("emailed_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_unique_constraint("uq_alert_dedupe", ["user_id", "dedupe_key"])
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "email_notifications", sa.Boolean(), server_default=sa.false(), nullable=False
            )
        )
        batch.add_column(sa.Column("money_checked_on", sa.Date(), nullable=True))
        batch.add_column(sa.Column("last_digest_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("last_digest_at")
        batch.drop_column("money_checked_on")
        batch.drop_column("email_notifications")
    with op.batch_alter_table("alerts") as batch:
        batch.drop_constraint("uq_alert_dedupe", type_="unique")
        batch.drop_column("emailed_at")
        batch.drop_column("dedupe_key")
