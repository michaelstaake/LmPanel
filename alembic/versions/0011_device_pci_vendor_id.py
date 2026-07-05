"""add pci_vendor_id to devices

Revision ID: 0011_device_pci_vendor_id
Revises: 0010_min_p
Create Date: 2026-07-04
"""

from alembic import op
import sqlalchemy as sa

revision = "0011_device_pci_vendor_id"
down_revision = "0010_min_p"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column("pci_vendor_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("devices", "pci_vendor_id")
