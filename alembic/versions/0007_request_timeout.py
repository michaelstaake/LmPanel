"""add request timeout setting

Revision ID: 0007_request_timeout
Revises: 0006_pool_max_slots_and_order
Create Date: 2026-06-17 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_request_timeout"
down_revision = "0006_pool_max_slots_and_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_settings", sa.Column("request_timeout_seconds", sa.Integer(), nullable=False, server_default="300"))


def downgrade() -> None:
    op.drop_column("app_settings", "request_timeout_seconds")
