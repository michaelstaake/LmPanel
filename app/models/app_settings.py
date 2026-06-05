from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    allow_anonymous_chat: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    users_can_register: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sitename: Mapped[str] = mapped_column(String(255), default="LmPanel", nullable=False)
    background_color: Mapped[str] = mapped_column(String(7), default="#efe8d2", nullable=False)
    background_image_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    background_image_mode: Mapped[str] = mapped_column(String(16), default="fill", nullable=False)
    active_web_search_provider_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    knowledge_base_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    input_price_per_1m: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    output_price_per_1m: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    public_url: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    letsencrypt_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cloudflare_api_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    cloudflare_turnstile_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cloudflare_turnstile_site_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cloudflare_turnstile_secret_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    usage_limit_tokens_60_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_limit_tokens_24_hours: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_limit_tokens_7_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_limit_tokens_30_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_limit_tools_60_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_limit_tools_24_hours: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_limit_tools_7_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_limit_tools_30_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    terms_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    terms_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    favicon_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    update_check_mode: Mapped[str] = mapped_column(String(16), default="disabled", nullable=False)