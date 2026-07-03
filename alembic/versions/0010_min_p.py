"""add min_p to model_configs

Revision ID: 0010_min_p
Revises: a1b2c3d4e5f6
Create Date: 2026-07-03
"""

from alembic import op
import sqlalchemy as sa

revision = "0010_min_p"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_configs",
        sa.Column("min_p", sa.Float(), nullable=False, server_default="0.05"),
    )


def downgrade() -> None:
    op.drop_column("model_configs", "min_p")
