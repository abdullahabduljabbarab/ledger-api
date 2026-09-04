"""Add outbox_events table for transactional outbox pattern

Revision ID: 002
Revises: 001
Create Date: 2026-09-04
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

PG_UUID_DEFAULT = sa.text("gen_random_uuid()")


def upgrade():
    op.create_table(
        "outbox_events",
        sa.Column(
            "id", UUID(as_uuid=True),
            primary_key=True, server_default=PG_UUID_DEFAULT,
        ),
        sa.Column("aggregate_type", sa.String(50), nullable=False),
        sa.Column("aggregate_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_outbox_published", "outbox_events", ["published_at"],
    )


def downgrade():
    op.drop_index("ix_outbox_published", table_name="outbox_events")
    op.drop_table("outbox_events")
