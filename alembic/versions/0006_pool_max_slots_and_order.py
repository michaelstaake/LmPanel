"""add pool max_slots and pool_order

Revision ID: 0006_pool_max_slots_and_order
Revises: 0005_last_reply_at
Create Date: 2026-06-12

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0006_pool_max_slots_and_order'
down_revision = '0005_last_reply_at'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('gpu_pools', sa.Column('max_slots', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('gpu_pools', sa.Column('pool_order', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('gpu_pools', 'pool_order')
    op.drop_column('gpu_pools', 'max_slots')
