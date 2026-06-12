from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

SPLIT_MODE_LAYER = "layer"
SPLIT_MODE_TENSOR = "tensor"
VALID_SPLIT_MODES = {SPLIT_MODE_LAYER, SPLIT_MODE_TENSOR}


class GpuPool(Base):
    __tablename__ = "gpu_pools"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="GPU Pool")
    vendor: Mapped[str] = mapped_column(String(32), nullable=False, default="nvidia")
    split_mode: Mapped[str] = mapped_column(String(16), nullable=False, default=SPLIT_MODE_LAYER)
    max_slots: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pool_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class GpuPoolDevice(Base):
    __tablename__ = "gpu_pool_devices"

    pool_id: Mapped[int] = mapped_column(ForeignKey("gpu_pools.id", ondelete="CASCADE"), primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
