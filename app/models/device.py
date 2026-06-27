from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    hardware_id: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    stable_hardware_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    stable_hardware_id_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    vendor: Mapped[str] = mapped_column(String(32), nullable=False)
    device_type: Mapped[str] = mapped_column(String(32), nullable=False, default="gpu")
    memory_mb: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # ``available`` reflects whether the device was physically detected by the most recent
    # authoritative probe. Distinct from ``enabled`` (user intent): a device can be enabled
    # but temporarily unavailable (e.g. inference runtime restarting / GPU driver re-init).
    # Used for soft-disable so we never destroy pool membership or model pins on transient
    # detection failures.
    available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default=true())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    max_threads: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_slots: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
