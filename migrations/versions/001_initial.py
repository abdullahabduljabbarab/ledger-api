"""Initial schema: accounts, transactions, ledger_entries + External Clearing seed

Revision ID: 001
Revises:
Create Date: 2026-09-04
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "001"
down_revision = None
branch_labels = None
depends_on = None

PG_UUID_DEFAULT = sa.text("gen_random_uuid()")
TXN_TYPE_ENUM = sa.Enum("deposit", "withdrawal", "transfer", name="transactiontype")


def upgrade():
    op.create_table(
        "accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=PG_UUID_DEFAULT),
        sa.Column("name", sa.String(), unique=True, nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "transactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=PG_UUID_DEFAULT),
        sa.Column("idempotency_key", sa.String(), unique=True, nullable=False),
        sa.Column("type", TXN_TYPE_ENUM, nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("reference", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "ledger_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=PG_UUID_DEFAULT),
        sa.Column(
            "transaction_id", UUID(as_uuid=True),
            sa.ForeignKey("transactions.id"), nullable=False,
        ),
        sa.Column(
            "account_id", UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"), nullable=False,
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
    )

    op.execute(
        "INSERT INTO accounts (name, is_system) VALUES ('External Clearing', true)"
    )


def downgrade():
    op.drop_table("ledger_entries")
    op.drop_table("transactions")
    op.drop_table("accounts")
    op.execute("DROP TYPE IF EXISTS transactiontype")
