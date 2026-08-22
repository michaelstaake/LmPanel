"""Drop unused 2FA, mail, and notification settings."""

from alembic import op
import sqlalchemy as sa


revision = "0019_drop_unused_2fa_mail_notifications"
down_revision = "0018_user_token_version"
branch_labels = None
depends_on = None

_DROP_COLUMNS = (
    "two_factor_enabled",
    "notifications_enabled",
    "notification_server_errors_enabled",
    "notification_ip_blocked_enabled",
    "notification_user_login_enabled",
    "notification_user_registers_enabled",
    "notification_usage_limit_reached_enabled",
    "mail_email_address",
    "mail_email_username",
    "mail_email_password",
    "mail_email_server",
    "mail_email_port",
    "mail_email_security",
    "mail_email_from_name",
)


def upgrade() -> None:
    with op.batch_alter_table("app_settings") as batch_op:
        for column_name in _DROP_COLUMNS:
            batch_op.drop_column(column_name)


def downgrade() -> None:
    with op.batch_alter_table("app_settings") as batch_op:
        batch_op.add_column(
            sa.Column("two_factor_enabled", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("notifications_enabled", sa.Boolean(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("notification_server_errors_enabled", sa.Boolean(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("notification_ip_blocked_enabled", sa.Boolean(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("notification_user_login_enabled", sa.Boolean(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("notification_user_registers_enabled", sa.Boolean(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("notification_usage_limit_reached_enabled", sa.Boolean(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("mail_email_address", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("mail_email_username", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("mail_email_password", sa.String(512), nullable=True))
        batch_op.add_column(sa.Column("mail_email_server", sa.String(255), nullable=True))
        batch_op.add_column(
            sa.Column("mail_email_port", sa.Integer(), nullable=False, server_default="587")
        )
        batch_op.add_column(
            sa.Column("mail_email_security", sa.String(16), nullable=False, server_default="starttls")
        )
        batch_op.add_column(sa.Column("mail_email_from_name", sa.String(255), nullable=True))
