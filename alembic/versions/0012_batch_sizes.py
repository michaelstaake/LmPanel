"""add batch_size and ubatch_size to model_configs

Revision ID: 0012_batch_sizes
Revises: 0011_device_pci_vendor_id
Create Date: 2026-07-04
"""

from alembic import op
import sqlalchemy as sa

revision = "0012_batch_sizes"
down_revision = "0011_device_pci_vendor_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_configs", sa.Column("batch_size", sa.Integer(), nullable=True))
    op.add_column("model_configs", sa.Column("ubatch_size", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("model_configs", "ubatch_size")
    op.drop_column("model_configs", "batch_size")
