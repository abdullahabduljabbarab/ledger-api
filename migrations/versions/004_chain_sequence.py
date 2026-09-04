"""Add chain sequence and re-anchor the hash chain

Concurrent writers previously read the chain tip without serialising, so two
transactions could link to the same predecessor and fork the chain. Ordering by
created_at made it worse: that column holds transaction start time, not commit
time, so the verification order did not match the link order.

This migration adds an explicit append-order column and rebuilds every hash in a
single deterministic pass, repairing chains damaged by the old behaviour.

Revision ID: 004
Revises: 003
Create Date: 2026-09-04
"""
import hashlib
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None

GENESIS_HASH = "0" * 64
AMOUNT_PRECISION = Decimal("0.01")


def upgrade():
    op.add_column(
        "transactions",
        sa.Column("chain_seq", sa.BigInteger(), nullable=True),
    )

    conn = op.get_bind()
    rows = conn.execute(sa.text(
        """
        SELECT id, idempotency_key, type::text AS type, amount, request_hash
        FROM transactions
        ORDER BY created_at ASC, id ASC
        """
    )).fetchall()

    prev_hash = GENESIS_HASH
    for seq, row in enumerate(rows, start=1):
        amount = Decimal(row.amount).quantize(AMOUNT_PRECISION)
        payload = (
            f"{row.id}|{row.idempotency_key}|{row.type}|"
            f"{amount}|{row.request_hash}|{prev_hash}"
        )
        chain_hash = hashlib.sha256(payload.encode()).hexdigest()
        conn.execute(
            sa.text(
                """
                UPDATE transactions
                SET chain_seq = :seq, prev_hash = :prev, chain_hash = :curr
                WHERE id = :id
                """
            ),
            {"seq": seq, "prev": prev_hash, "curr": chain_hash, "id": row.id},
        )
        prev_hash = chain_hash

    op.create_unique_constraint(
        "uq_transactions_chain_seq", "transactions", ["chain_seq"]
    )


def downgrade():
    op.drop_constraint("uq_transactions_chain_seq", "transactions", type_="unique")
    op.drop_column("transactions", "chain_seq")
