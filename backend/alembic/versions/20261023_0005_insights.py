"""insights

Revision ID: 4330028a31f8
Revises: fac241682015
Create Date: 2026-10-23 17:39:19.178435
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4330028a31f8"
down_revision: str | None = "fac241682015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:

    op.create_table(
        "fund_schemes",
        sa.Column("scheme_code", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("fund_house", sa.String(length=150), nullable=True),
        sa.Column("category", sa.String(length=200), nullable=True),
        sa.Column("isin", sa.String(length=12), nullable=True),
        sa.Column("nav", sa.String(length=24), nullable=True),
        sa.Column("nav_date", sa.Date(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("scheme_code", name=op.f("pk_fund_schemes")),
    )
    op.create_index(op.f("ix_fund_schemes_name"), "fund_schemes", ["name"], unique=False)
    op.create_table(
        "gold_prices",
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("price_per_ounce_minor", sa.BigInteger(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gold_prices")),
    )
    op.create_index(
        op.f("ix_gold_prices_observed_at"), "gold_prices", ["observed_at"], unique=False
    )
    op.create_table(
        "fund_navs",
        sa.Column("scheme_code", sa.Integer(), nullable=False),
        sa.Column("nav_date", sa.Date(), nullable=False),
        sa.Column("nav", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["scheme_code"],
            ["fund_schemes.scheme_code"],
            name=op.f("fk_fund_navs_scheme_code_fund_schemes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("scheme_code", "nav_date", name=op.f("pk_fund_navs")),
    )
    op.create_table(
        "watched_funds",
        sa.Column("scheme_code", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["scheme_code"],
            ["fund_schemes.scheme_code"],
            name=op.f("fk_watched_funds_scheme_code_fund_schemes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_watched_funds_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_watched_funds")),
        sa.UniqueConstraint("user_id", "scheme_code", name="uq_watched_funds_user_scheme"),
    )
    op.create_index(op.f("ix_watched_funds_user_id"), "watched_funds", ["user_id"], unique=False)


def downgrade() -> None:

    op.drop_index(op.f("ix_watched_funds_user_id"), table_name="watched_funds")
    op.drop_table("watched_funds")
    op.drop_table("fund_navs")
    op.drop_index(op.f("ix_gold_prices_observed_at"), table_name="gold_prices")
    op.drop_table("gold_prices")
    op.drop_index(op.f("ix_fund_schemes_name"), table_name="fund_schemes")
    op.drop_table("fund_schemes")
