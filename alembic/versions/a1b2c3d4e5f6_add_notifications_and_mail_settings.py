"""add notifications and mail settings

Revision ID: a1b2c3d4e5f6
Revises: 0004_brute_force
Create Date: 2026-06-08 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "0004_brute_force"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_settings", sa.Column("notifications_enabled", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column("app_settings", sa.Column("notification_server_errors_enabled", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column("app_settings", sa.Column("notification_ip_blocked_enabled", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column("app_settings", sa.Column("notification_user_login_enabled", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column("app_settings", sa.Column("notification_user_registers_enabled", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column("app_settings", sa.Column("notification_usage_limit_reached_enabled", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column("app_settings", sa.Column("mail_email_address", sa.String(255), nullable=True))
    op.add_column("app_settings", sa.Column("mail_email_username", sa.String(255), nullable=True))
    op.add_column("app_settings", sa.Column("mail_email_password", sa.String(512), nullable=True))
    op.add_column("app_settings", sa.Column("mail_email_server", sa.String(255), nullable=True))
    op.add_column("app_settings", sa.Column("mail_email_port", sa.Integer(), nullable=False, server_default="587"))
    op.add_column("app_settings", sa.Column("mail_email_security", sa.String(16), nullable=False, server_default="starttls"))
    op.add_column("app_settings", sa.Column("mail_email_from_name", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("app_settings", "mail_email_from_name")
    op.drop_column("app_settings", "mail_email_security")
    op.drop_column("app_settings", "mail_email_port")
    op.drop_column("app_settings", "mail_email_server")
    op.drop_column("app_settings", "mail_email_password")
    op.drop_column("app_settings", "mail_email_username")
    op.drop_column("app_settings", "mail_email_address")
    op.drop_column("app_settings", "notification_usage_limit_reached_enabled")
    op.drop_column("app_settings", "notification_user_registers_enabled")
    op.drop_column("app_settings", "notification_user_login_enabled")
    op.drop_column("app_settings", "notification_ip_blocked_enabled")
    op.drop_column("app_settings", "notification_server_errors_enabled")
    op.drop_column("app_settings", "notifications_enabled")
