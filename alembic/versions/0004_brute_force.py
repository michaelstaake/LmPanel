"""add brute force protection settings

Revision ID: 0004_brute_force
Revises: 0003_favicon_path
Create Date: 2026-06-08

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0004_brute_force"
down_revision = "0003_favicon_path"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_settings", sa.Column("brute_force_enabled", sa.Boolean(), nullable=False, server_default="1"))
    op.add_column("app_settings", sa.Column("brute_force_max_failures", sa.Integer(), nullable=False, server_default="10"))
    op.add_column("app_settings", sa.Column("brute_force_window_minutes", sa.Integer(), nullable=False, server_default="15"))
    op.add_column("app_settings", sa.Column("brute_force_block_minutes", sa.Integer(), nullable=False, server_default="15"))


def downgrade() -> None:
    op.drop_column("app_settings", "brute_force_block_minutes")
    op.drop_column("app_settings", "brute_force_window_minutes")
    op.drop_column("app_settings", "brute_force_max_failures")
    op.drop_column("app_settings", "brute_force_enabled")
