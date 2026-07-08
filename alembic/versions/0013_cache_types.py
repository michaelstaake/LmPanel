"""Add per-model KV cache quantization types."""

from alembic import op
import sqlalchemy as sa

revision = "0013_cache_types"
down_revision = "0012_batch_sizes"


def upgrade() -> None:
    op.add_column("model_configs", sa.Column("cache_type_k", sa.String(length=16), nullable=True))
    op.add_column("model_configs", sa.Column("cache_type_v", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("model_configs", "cache_type_v")
    op.drop_column("model_configs", "cache_type_k")
