"""market data

Revision ID: 8d33153536f6
Revises: 4b2454350252
Create Date: 2026-10-23 15:43:02.823783
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8d33153536f6"
down_revision: str | None = "4b2454350252"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:

    op.create_table(
        "fx_rates",
        sa.Column("pivot", sa.String(length=3), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("rate", sa.String(length=40), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fx_rates")),
        sa.UniqueConstraint("pivot", "currency", "rate_date", name="uq_fx_rates_pair_day"),
    )
    op.create_index(op.f("ix_fx_rates_rate_date"), "fx_rates", ["rate_date"], unique=False)
    op.create_table(
        "alerts",
        sa.Column("item_id", sa.Uuid(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "price_target",
                "price_drop",
                "check_failing",
                "back_in_stock",
                name="alertkind",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["planned_items.id"],
            name=op.f("fk_alerts_item_id_planned_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_alerts_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
    )
    op.create_index(op.f("ix_alerts_created_at"), "alerts", ["created_at"], unique=False)
    op.create_index(op.f("ix_alerts_item_id"), "alerts", ["item_id"], unique=False)
    op.create_index(op.f("ix_alerts_user_id"), "alerts", ["user_id"], unique=False)
    op.create_table(
        "price_observations",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "method",
            sa.Enum(
                "json_ld",
                "microdata",
                "opengraph",
                "manual",
                name="observationmethod",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column("confidence", sa.String(length=10), nullable=False),
        sa.Column(
            "availability",
            sa.Enum(
                "in_stock",
                "out_of_stock",
                "preorder",
                "unknown",
                name="availability",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column("source_name", sa.String(length=200), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("page_title", sa.String(length=300), nullable=True),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "amount_minor > 0", name=op.f("ck_price_observations_observation_positive")
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["planned_items.id"],
            name=op.f("fk_price_observations_item_id_planned_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_price_observations_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_observations")),
    )
    op.create_index(
        op.f("ix_price_observations_item_id"), "price_observations", ["item_id"], unique=False
    )
    op.create_index(
        op.f("ix_price_observations_observed_at"),
        "price_observations",
        ["observed_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_price_observations_user_id"), "price_observations", ["user_id"], unique=False
    )
    op.add_column(
        "planned_items",
        sa.Column("track_price", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "planned_items", sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "planned_items", sa.Column("last_check_error", sa.String(length=300), nullable=True)
    )
    op.add_column(
        "planned_items",
        sa.Column("failed_checks", sa.SmallInteger(), server_default="0", nullable=False),
    )


def downgrade() -> None:

    op.drop_column("planned_items", "failed_checks")
    op.drop_column("planned_items", "last_check_error")
    op.drop_column("planned_items", "last_checked_at")
    op.drop_column("planned_items", "track_price")
    op.drop_index(op.f("ix_price_observations_user_id"), table_name="price_observations")
    op.drop_index(op.f("ix_price_observations_observed_at"), table_name="price_observations")
    op.drop_index(op.f("ix_price_observations_item_id"), table_name="price_observations")
    op.drop_table("price_observations")
    op.drop_index(op.f("ix_alerts_user_id"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_item_id"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_created_at"), table_name="alerts")
    op.drop_table("alerts")
    op.drop_index(op.f("ix_fx_rates_rate_date"), table_name="fx_rates")
    op.drop_table("fx_rates")
