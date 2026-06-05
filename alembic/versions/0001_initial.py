"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-05
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _seed_data() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text(
            "INSERT INTO packages (id, name, is_admin_package, is_default_package, "
            "usage_limit_tokens_60_minutes, usage_limit_tokens_24_hours, "
            "usage_limit_tokens_7_days, usage_limit_tokens_30_days, "
            "usage_limit_tools_60_minutes, usage_limit_tools_24_hours, "
            "usage_limit_tools_7_days, usage_limit_tools_30_days) "
            "VALUES "
            "(1, 'Unlimited', 1, 0, 0, 0, 0, 0, 0, 0, 0, 0), "
            "(2, 'Default', 0, 1, 0, 0, 0, 0, 0, 0, 0, 0)"
        )
    )

    conn.execute(
        sa.text(
            "INSERT INTO web_search_providers (provider_type, enabled, api_key, result_count) "
            "VALUES ('serper', 0, NULL, 5)"
        )
    )


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("allow_anonymous_chat", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("users_can_register", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sitename", sa.String(length=255), nullable=False, server_default="LmPanel"),
        sa.Column("background_color", sa.String(length=7), nullable=False, server_default="#efe8d2"),
        sa.Column("background_image_path", sa.String(length=255), nullable=True),
        sa.Column("background_image_mode", sa.String(length=16), nullable=False, server_default="fill"),
        sa.Column("active_web_search_provider_id", sa.Integer(), nullable=True),
        sa.Column("knowledge_base_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("input_price_per_1m", sa.Float(), nullable=False, server_default="0"),
        sa.Column("output_price_per_1m", sa.Float(), nullable=False, server_default="0"),
        sa.Column("public_url", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("letsencrypt_email", sa.String(length=255), nullable=True),
        sa.Column("cloudflare_api_token", sa.Text(), nullable=True),
        sa.Column("cloudflare_turnstile_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cloudflare_turnstile_site_key", sa.String(length=255), nullable=True),
        sa.Column("cloudflare_turnstile_secret_key", sa.String(length=255), nullable=True),
        sa.Column("two_factor_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("usage_limit_tokens_60_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("usage_limit_tokens_24_hours", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("usage_limit_tokens_7_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("usage_limit_tokens_30_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("usage_limit_tools_60_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("usage_limit_tools_24_hours", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("usage_limit_tools_7_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("usage_limit_tools_30_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("terms_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("terms_content", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(
        sa.table(
            "app_settings",
            sa.column("id", sa.Integer()),
            sa.column("allow_anonymous_chat", sa.Boolean()),
            sa.column("users_can_register", sa.Boolean()),
            sa.column("sitename", sa.String()),
        ),
        [{"id": 1, "allow_anonymous_chat": True, "users_can_register": False, "sitename": "LmPanel"}],
    )

    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hardware_id", sa.String(length=120), nullable=False),
        sa.Column("stable_hardware_id", sa.String(length=160), nullable=True),
        sa.Column("stable_hardware_id_source", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("vendor", sa.String(length=32), nullable=False),
        sa.Column("device_type", sa.String(length=32), nullable=False),
        sa.Column("memory_mb", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("max_threads", sa.Integer(), nullable=False),
        sa.Column("max_slots", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hardware_id"),
    )
    op.create_index(op.f("ix_devices_id"), "devices", ["id"], unique=False)

    op.create_table(
        "gpu_pools",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("vendor", sa.String(length=32), nullable=False),
        sa.Column("split_mode", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_gpu_pools_id"), "gpu_pools", ["id"], unique=False)

    op.create_table(
        "packages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("is_admin_package", sa.Boolean(), nullable=False),
        sa.Column("is_default_package", sa.Boolean(), nullable=False),
        sa.Column("usage_limit_tokens_60_minutes", sa.Integer(), nullable=False),
        sa.Column("usage_limit_tokens_24_hours", sa.Integer(), nullable=False),
        sa.Column("usage_limit_tokens_7_days", sa.Integer(), nullable=False),
        sa.Column("usage_limit_tokens_30_days", sa.Integer(), nullable=False),
        sa.Column("usage_limit_tools_60_minutes", sa.Integer(), nullable=False),
        sa.Column("usage_limit_tools_24_hours", sa.Integer(), nullable=False),
        sa.Column("usage_limit_tools_7_days", sa.Integer(), nullable=False),
        sa.Column("usage_limit_tools_30_days", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_packages_id"), "packages", ["id"], unique=False)

    op.create_table(
        "web_search_providers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_type", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_type"),
    )
    op.create_index(op.f("ix_web_search_providers_id"), "web_search_providers", ["id"], unique=False)

    op.create_table(
        "gpu_pool_devices",
        sa.Column("pool_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pool_id"], ["gpu_pools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("pool_id", "device_id"),
    )

    op.create_table(
        "model_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("model_dir_name", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("alias", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("chat_template", sa.Text(), nullable=False),
        sa.Column("context_length", sa.Integer(), nullable=False),
        sa.Column("gpu_layers", sa.Integer(), nullable=False),
        sa.Column("threads", sa.Integer(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("top_p", sa.Float(), nullable=False),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("presence_penalty", sa.Float(), nullable=False),
        sa.Column("repetition_penalty", sa.Float(), nullable=False),
        sa.Column("tool_calling_enabled", sa.Boolean(), nullable=False),
        sa.Column("discourage_thinking", sa.Boolean(), nullable=False),
        sa.Column("default_thinking_enabled", sa.Boolean(), nullable=False),
        sa.Column("thinking_capability", sa.String(length=16), nullable=False),
        sa.Column("vision_enabled", sa.Boolean(), nullable=False),
        sa.Column("web_search_enabled", sa.Boolean(), nullable=False),
        sa.Column("rag_enabled", sa.Boolean(), nullable=False),
        sa.Column("flash_attention_enabled", sa.Boolean(), nullable=False),
        sa.Column("memory_mapping_enabled", sa.Boolean(), nullable=False),
        sa.Column("mmproj_file_name", sa.String(length=255), nullable=True),
        sa.Column("assignment_mode", sa.String(length=32), nullable=False),
        sa.Column("pinned_device_id", sa.Integer(), nullable=True),
        sa.Column("pinned_pool_id", sa.Integer(), nullable=True),
        sa.Column("activated", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["pinned_device_id"], ["devices.id"]),
        sa.ForeignKeyConstraint(["pinned_pool_id"], ["gpu_pools.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alias"),
        sa.UniqueConstraint("file_name"),
        sa.UniqueConstraint("model_dir_name"),
    )
    op.create_index(op.f("ix_model_configs_id"), "model_configs", ["id"], unique=False)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("package_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["package_id"], ["packages.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("username"),
    )
    op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)

    op.create_table(
        "activity_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("username", sa.String(length=120), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_activity_logs_created_at", "activity_logs", ["created_at"])
    op.create_index("ix_activity_logs_event_type", "activity_logs", ["event_type"])

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("key_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_api_keys_id"), "api_keys", ["id"], unique=False)

    op.create_table(
        "chats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chats_id"), "chats", ["id"], unique=False)

    op.create_table(
        "inference_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model_config_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.ForeignKeyConstraint(["model_config_id"], ["model_configs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_inference_jobs_id"), "inference_jobs", ["id"], unique=False)

    op.create_table(
        "knowledge_base_categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_base_categories_id"), "knowledge_base_categories", ["id"], unique=False)
    op.create_index(op.f("ix_knowledge_base_categories_user_id"), "knowledge_base_categories", ["user_id"], unique=False)

    op.create_table(
        "token_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_token_usage_created_at"), "token_usage", ["created_at"], unique=False)
    op.create_index(op.f("ix_token_usage_id"), "token_usage", ["id"], unique=False)
    op.create_index(op.f("ix_token_usage_total_tokens"), "token_usage", ["total_tokens"], unique=False)
    op.create_index(op.f("ix_token_usage_user_id"), "token_usage", ["user_id"], unique=False)

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("elapsed_seconds", sa.Float(), nullable=True),
        sa.Column("tokens_per_second", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chat_messages_id"), "chat_messages", ["id"], unique=False)

    op.create_table(
        "knowledge_base_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["knowledge_base_categories.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_base_documents_category_id"), "knowledge_base_documents", ["category_id"], unique=False)
    op.create_index(op.f("ix_knowledge_base_documents_id"), "knowledge_base_documents", ["id"], unique=False)
    op.create_index(op.f("ix_knowledge_base_documents_user_id"), "knowledge_base_documents", ["user_id"], unique=False)

    _seed_data()


def downgrade() -> None:
    op.drop_index(op.f("ix_knowledge_base_documents_user_id"), table_name="knowledge_base_documents")
    op.drop_index(op.f("ix_knowledge_base_documents_id"), table_name="knowledge_base_documents")
    op.drop_index(op.f("ix_knowledge_base_documents_category_id"), table_name="knowledge_base_documents")
    op.drop_table("knowledge_base_documents")
    op.drop_index(op.f("ix_chat_messages_id"), table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index(op.f("ix_token_usage_user_id"), table_name="token_usage")
    op.drop_index(op.f("ix_token_usage_total_tokens"), table_name="token_usage")
    op.drop_index(op.f("ix_token_usage_id"), table_name="token_usage")
    op.drop_index(op.f("ix_token_usage_created_at"), table_name="token_usage")
    op.drop_table("token_usage")
    op.drop_index(op.f("ix_knowledge_base_categories_user_id"), table_name="knowledge_base_categories")
    op.drop_index(op.f("ix_knowledge_base_categories_id"), table_name="knowledge_base_categories")
    op.drop_table("knowledge_base_categories")
    op.drop_index(op.f("ix_inference_jobs_id"), table_name="inference_jobs")
    op.drop_table("inference_jobs")
    op.drop_index(op.f("ix_chats_id"), table_name="chats")
    op.drop_table("chats")
    op.drop_index(op.f("ix_api_keys_id"), table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_index("ix_activity_logs_event_type", table_name="activity_logs")
    op.drop_index("ix_activity_logs_created_at", table_name="activity_logs")
    op.drop_table("activity_logs")
    op.drop_index(op.f("ix_users_id"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_model_configs_id"), table_name="model_configs")
    op.drop_table("model_configs")
    op.drop_table("gpu_pool_devices")
    op.drop_index(op.f("ix_web_search_providers_id"), table_name="web_search_providers")
    op.drop_table("web_search_providers")
    op.drop_index(op.f("ix_packages_id"), table_name="packages")
    op.drop_table("packages")
    op.drop_index(op.f("ix_gpu_pools_id"), table_name="gpu_pools")
    op.drop_table("gpu_pools")
    op.drop_index(op.f("ix_devices_id"), table_name="devices")
    op.drop_table("devices")
    op.drop_table("app_settings")
