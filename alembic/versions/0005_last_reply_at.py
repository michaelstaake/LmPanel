"""add last_reply_at to chats
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_last_reply_at"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chats",
        sa.Column("last_reply_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chats", "last_reply_at")
