"""Seed Payment Suspense and Settlement Clearing system accounts

These are the two system accounts the payment orchestrator moves funds through:
reserve sends customer funds to Payment Suspense, capture sends them on to
Settlement Clearing, and release returns them to the customer. They are owned by
the ledger because the ledger owns financial state; the orchestrator only holds
their fixed IDs and settles through the ledger API.

The IDs are fixed so they are stable and known across every environment.

Revision ID: 005
Revises: 004
Create Date: 2026-09-05
"""
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None

PAYMENT_SUSPENSE_ID = "a0000000-0000-4000-8000-000000000001"
SETTLEMENT_CLEARING_ID = "a0000000-0000-4000-8000-000000000002"


def upgrade():
    op.execute(
        "INSERT INTO accounts (id, name, is_system) VALUES "
        f"('{PAYMENT_SUSPENSE_ID}', 'Payment Suspense', true)"
    )
    op.execute(
        "INSERT INTO accounts (id, name, is_system) VALUES "
        f"('{SETTLEMENT_CLEARING_ID}', 'Settlement Clearing', true)"
    )


def downgrade():
    op.execute(
        "DELETE FROM accounts WHERE id IN "
        f"('{PAYMENT_SUSPENSE_ID}', '{SETTLEMENT_CLEARING_ID}')"
    )
