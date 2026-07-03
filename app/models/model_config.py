from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    model_dir_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    alias: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    chat_template: Mapped[str] = mapped_column(Text, default="", nullable=False)
    context_length: Mapped[int] = mapped_column(Integer, default=32768, nullable=False)
    gpu_layers: Mapped[int] = mapped_column(Integer, default=99, nullable=False)
    threads: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    top_p: Mapped[float] = mapped_column(Float, default=0.95, nullable=False)
    min_p: Mapped[float] = mapped_column(Float, default=0.05, nullable=False)
    top_k: Mapped[int] = mapped_column(Integer, default=40, nullable=False)
    presence_penalty: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    repetition_penalty: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    tool_calling_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    discourage_thinking: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_thinking_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    thinking_capability: Mapped[str] = mapped_column(String(16), default="auto", nullable=False)
    vision_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    web_search_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rag_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    flash_attention_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    memory_mapping_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    mmproj_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assignment_mode: Mapped[str] = mapped_column(String(32), default="auto", nullable=False)
    pinned_device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"), nullable=True)
    pinned_pool_id: Mapped[int | None] = mapped_column(ForeignKey("gpu_pools.id"), nullable=True)
    activated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
