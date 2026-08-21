"""Add hide_footer_info to app_settings."""

from alembic import op
import sqlalchemy as sa

revision = "0016_hide_footer_info"
down_revision = "0015_thinking_levels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("hide_footer_info", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "hide_footer_info")
