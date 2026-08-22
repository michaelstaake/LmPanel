"""Add user token version for session revocation."""

from alembic import op
import sqlalchemy as sa


revision = "0018_user_token_version"
down_revision = "0017_token_usage_api_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("token_version", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("token_version")
