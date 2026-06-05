"""add update_check_mode to app_settings

Revision ID: 0002_update_check
Revises: 0001_initial
Create Date: 2026-06-05
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_update_check"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("update_check_mode", sa.String(length=16), nullable=False, server_default="disabled"),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "update_check_mode")
