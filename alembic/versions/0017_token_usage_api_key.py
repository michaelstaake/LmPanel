"""Add api_key_id to token_usage for per-key tracking."""

from alembic import op
import sqlalchemy as sa

revision = "0017_token_usage_api_key"
down_revision = "0016_hide_footer_info"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("token_usage") as batch_op:
        batch_op.add_column(sa.Column("api_key_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_token_usage_api_key_id", ["api_key_id"])
        batch_op.create_foreign_key(
            "fk_token_usage_api_key_id_api_keys",
            "api_keys",
            ["api_key_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("token_usage") as batch_op:
        batch_op.drop_constraint("fk_token_usage_api_key_id_api_keys", type_="foreignkey")
        batch_op.drop_index("ix_token_usage_api_key_id")
        batch_op.drop_column("api_key_id")
