"""Add per-model MTP (multi-token prediction) settings."""

from alembic import op
import sqlalchemy as sa

revision = "0014_mtp"
down_revision = "0013_cache_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_configs",
        sa.Column("mtp_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "model_configs",
        sa.Column("mtp_draft_n", sa.Integer(), nullable=False, server_default="3"),
    )


def downgrade() -> None:
    op.drop_column("model_configs", "mtp_draft_n")
    op.drop_column("model_configs", "mtp_enabled")
