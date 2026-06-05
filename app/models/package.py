from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Package(Base):
    __tablename__ = "packages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    is_admin_package: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_default_package: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    usage_limit_tokens_60_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_limit_tokens_24_hours: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_limit_tokens_7_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_limit_tokens_30_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_limit_tools_60_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_limit_tools_24_hours: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_limit_tools_7_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_limit_tools_30_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
