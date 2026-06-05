"""add favicon_path to app_settings

Revision ID: 0003_favicon_path
Revises: 0002_update_check
Create Date: 2026-06-05
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_favicon_path"
down_revision = "0002_update_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("favicon_path", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "favicon_path")
