"""add logo_path to app_settings

Revision ID: 0008_logo_path
Revises: 0007_request_timeout
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_logo_path"
down_revision = "0007_request_timeout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("logo_path", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "logo_path")
