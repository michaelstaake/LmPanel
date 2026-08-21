"""Add default thinking effort level for models that support it."""

from alembic import op
import sqlalchemy as sa

revision = "0015_thinking_levels"
down_revision = "0014_mtp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_configs",
        sa.Column("default_thinking_level", sa.String(length=16), nullable=False, server_default="medium"),
    )


def downgrade() -> None:
    op.drop_column("model_configs", "default_thinking_level")
