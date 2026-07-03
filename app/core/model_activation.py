"""Guards against concurrent model loads exhausting host RAM."""

from __future__ import annotations

import os

import psutil

from app.models.model_config import ModelConfig


class InsufficientHostRamError(RuntimeError):
    """Raised when activating another model would risk host RAM exhaustion."""


def estimate_model_file_size_mb(model: ModelConfig) -> int:
    try:
        return int(os.path.getsize(model.file_path) / (1024 * 1024))
    except OSError:
        return 0


def assert_host_ram_for_activation(
    *,
    model_size_mb: int,
    min_free_mb: int,
    headroom_ratio: float,
) -> None:
    """Require enough free host RAM before starting another model load.

    Vulkan/RADV model loads use substantial host-side staging memory in addition
    to VRAM. Concurrent loads are the main OOM trigger on multi-GPU hosts.
    """
    available_mb = int(psutil.virtual_memory().available / (1024 * 1024))
    estimated_need_mb = int(model_size_mb * headroom_ratio) if model_size_mb > 0 else 0
    required_mb = max(min_free_mb, estimated_need_mb)
    if available_mb < required_mb:
        raise InsufficientHostRamError(
            f"Insufficient host RAM: {available_mb} MB available, need at least {required_mb} MB "
            f"before loading another model"
        )
