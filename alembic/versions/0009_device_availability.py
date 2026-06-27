"""device availability (soft-disable) columns

Revision ID: 0009_device_availability
Revises: 0008_logo_path
Create Date: 2026-06-26
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_device_availability"
down_revision = "0008_logo_path"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "devices",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("devices", "last_seen_at")
    op.drop_column("devices", "available")
