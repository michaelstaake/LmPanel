"""add AMD NPU metadata fields to model_configs

Revision ID: 0004_anpu_model_fields
Revises: 0003_favicon_path
Create Date: 2026-06-08
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_anpu_model_fields"
down_revision = "0003_favicon_path"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_configs", sa.Column("anpu_architecture", sa.String(length=64), nullable=True))
    op.add_column(
        "model_configs",
        sa.Column("anpu_compatible", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("model_configs", sa.Column("anpu_flm_tag", sa.String(length=120), nullable=True))
    op.add_column(
        "model_configs",
        sa.Column("anpu_conversion_status", sa.String(length=32), nullable=False, server_default="none"),
    )
    op.add_column("model_configs", sa.Column("anpu_conversion_error", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("model_configs", "anpu_conversion_error")
    op.drop_column("model_configs", "anpu_conversion_status")
    op.drop_column("model_configs", "anpu_flm_tag")
    op.drop_column("model_configs", "anpu_compatible")
    op.drop_column("model_configs", "anpu_architecture")
