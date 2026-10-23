"""initial schema

Revision ID: 1c057761cb4d
Revises:
Create Date: 2026-10-23 12:24:16.318482
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1c057761cb4d"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:

    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("reserve_months", sa.SmallInteger(), nullable=False),
        sa.Column("reserve_buffer_minor", sa.BigInteger(), nullable=False),
        sa.Column(
            "llm_mode",
            sa.Enum("mock", "anthropic", name="llmmode", native_enum=False, length=24),
            nullable=False,
        ),
        sa.Column("llm_api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("llm_api_key_hint", sa.String(length=8), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("reserve_buffer_minor >= 0", name=op.f("ck_users_reserve_buffer")),
        sa.CheckConstraint(
            "reserve_months >= 0 AND reserve_months <= 24", name=op.f("ck_users_reserve_months")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_table(
        "accounts",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "bank",
                "cash",
                "wallet",
                "savings",
                "other",
                name="accountkind",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("opening_balance_minor", sa.BigInteger(), nullable=False),
        sa.Column("include_in_planning", sa.Boolean(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_accounts_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
    )
    op.create_index(op.f("ix_accounts_user_id"), "accounts", ["user_id"], unique=False)
    op.create_table(
        "audit_events",
        sa.Column("entity", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_audit_events_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(op.f("ix_audit_events_entity_id"), "audit_events", ["entity_id"], unique=False)
    op.create_index(op.f("ix_audit_events_user_id"), "audit_events", ["user_id"], unique=False)
    op.create_table(
        "obligations",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "frequency",
            sa.Enum(
                "once",
                "weekly",
                "monthly",
                "quarterly",
                "yearly",
                name="frequency",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column("anchor_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("essential", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("amount_minor > 0", name=op.f("ck_obligations_obligation_positive")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_obligations_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_obligations")),
    )
    op.create_index(op.f("ix_obligations_user_id"), "obligations", ["user_id"], unique=False)
    op.create_table(
        "planned_items",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "tier",
            sa.Enum("need", "want", "desire", name="tier", native_enum=False, length=24),
            nullable=False,
        ),
        sa.Column(
            "kind",
            sa.Enum(
                "product",
                "service",
                "travel",
                "experience",
                "subscription",
                "other",
                name="itemkind",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "planned",
                "purchased",
                "postponed",
                "dropped",
                name="itemstatus",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column("priority", sa.SmallInteger(), nullable=False),
        sa.Column("estimated_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "price_source",
            sa.Enum("user", "link", "estimate", name="pricesource", native_enum=False, length=24),
            nullable=False,
        ),
        sa.Column("price_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quantity", sa.SmallInteger(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column(
            "deadline_type",
            sa.Enum("hard", "soft", "none", name="deadlinetype", native_enum=False, length=24),
            nullable=False,
        ),
        sa.Column("lead_time_days", sa.SmallInteger(), nullable=False),
        sa.Column("max_price_minor", sa.BigInteger(), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("purchased_on", sa.Date(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "estimated_price_minor >= 0", name=op.f("ck_planned_items_price_non_negative")
        ),
        sa.CheckConstraint(
            "lead_time_days BETWEEN 0 AND 365", name=op.f("ck_planned_items_lead_time_range")
        ),
        sa.CheckConstraint(
            "priority BETWEEN 1 AND 5", name=op.f("ck_planned_items_priority_range")
        ),
        sa.CheckConstraint(
            "quantity BETWEEN 1 AND 1000", name=op.f("ck_planned_items_quantity_range")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_planned_items_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_planned_items")),
    )
    op.create_index(op.f("ix_planned_items_status"), "planned_items", ["status"], unique=False)
    op.create_index(op.f("ix_planned_items_tier"), "planned_items", ["tier"], unique=False)
    op.create_index(op.f("ix_planned_items_user_id"), "planned_items", ["user_id"], unique=False)
    op.create_table(
        "refresh_tokens",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_refresh_tokens_family_id"), "refresh_tokens", ["family_id"], unique=False
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)
    op.create_table(
        "income_streams",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "frequency",
            sa.Enum(
                "once",
                "weekly",
                "monthly",
                "quarterly",
                "yearly",
                name="frequency",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column("anchor_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("subject_to_shocks", sa.Boolean(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("amount_minor > 0", name=op.f("ck_income_streams_income_positive")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_income_streams_account_id_accounts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_income_streams_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_income_streams")),
    )
    op.create_index(op.f("ix_income_streams_user_id"), "income_streams", ["user_id"], unique=False)
    op.create_table(
        "transactions",
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("income", "expense", name="txnkind", native_enum=False, length=24),
            nullable=False,
        ),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("planned_item_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("amount_minor > 0", name=op.f("ck_transactions_txn_positive")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_transactions_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["planned_item_id"],
            ["planned_items.id"],
            name=op.f("fk_transactions_planned_item_id_planned_items"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_transactions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
    )
    op.create_index(
        op.f("ix_transactions_account_id"), "transactions", ["account_id"], unique=False
    )
    op.create_index(
        op.f("ix_transactions_occurred_on"), "transactions", ["occurred_on"], unique=False
    )
    op.create_index(op.f("ix_transactions_user_id"), "transactions", ["user_id"], unique=False)


def downgrade() -> None:

    op.drop_index(op.f("ix_transactions_user_id"), table_name="transactions")
    op.drop_index(op.f("ix_transactions_occurred_on"), table_name="transactions")
    op.drop_index(op.f("ix_transactions_account_id"), table_name="transactions")
    op.drop_table("transactions")
    op.drop_index(op.f("ix_income_streams_user_id"), table_name="income_streams")
    op.drop_table("income_streams")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_family_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index(op.f("ix_planned_items_user_id"), table_name="planned_items")
    op.drop_index(op.f("ix_planned_items_tier"), table_name="planned_items")
    op.drop_index(op.f("ix_planned_items_status"), table_name="planned_items")
    op.drop_table("planned_items")
    op.drop_index(op.f("ix_obligations_user_id"), table_name="obligations")
    op.drop_table("obligations")
    op.drop_index(op.f("ix_audit_events_user_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_entity_id"), table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index(op.f("ix_accounts_user_id"), table_name="accounts")
    op.drop_table("accounts")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
