"""Add tamper-evident hash chain columns to transactions

Revision ID: 003
Revises: 002
Create Date: 2026-09-04
"""
import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "transactions",
        sa.Column("prev_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column("chain_hash", sa.String(64), nullable=True),
    )


def downgrade():
    op.drop_column("transactions", "chain_hash")
    op.drop_column("transactions", "prev_hash")
