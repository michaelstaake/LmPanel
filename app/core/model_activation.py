"""Guards against concurrent model loads exhausting host RAM."""

from __future__ import annotations

import os
from pathlib import Path

import psutil

from app.core.config import get_settings
from app.core.gguf_shards import collect_shard_files, parse_gguf_shard_name
from app.models.model_config import ModelConfig


class InsufficientHostRamError(RuntimeError):
    """Raised when activating another model would risk host RAM exhaustion."""


class InsufficientGttError(RuntimeError):
    """Raised when a target GPU's GTT usage indicates prior VRAM spillover."""


class InsufficientVramError(RuntimeError):
    """Raised when estimated VRAM need exceeds available GPU memory."""


def estimate_model_file_size_mb(model: ModelConfig) -> int:
    model_dir = Path(get_settings().models_dir) / model.model_dir_name
    shard_paths = collect_shard_files(model_dir, model.file_name)
    if len(shard_paths) > 1 or parse_gguf_shard_name(model.file_name) is not None:
        total_bytes = 0
        for path in shard_paths:
            try:
                total_bytes += path.stat().st_size
            except OSError:
                continue
        if total_bytes > 0:
            return int(total_bytes / (1024 * 1024))

    try:
        return int(os.path.getsize(model.file_path) / (1024 * 1024))
    except OSError:
        return 0


def resolve_activation_headroom_ratio(
    *,
    gpu_layers: int,
    memory_mapping_enabled: bool,
    cpu_headroom_ratio: float,
    gpu_mmap_headroom_ratio: float,
    gpu_no_mmap_headroom_ratio: float,
) -> float:
    if gpu_layers == 0:
        return cpu_headroom_ratio
    if memory_mapping_enabled:
        return gpu_mmap_headroom_ratio
    return gpu_no_mmap_headroom_ratio


def assert_host_ram_for_activation(
    *,
    model_size_mb: int,
    min_free_mb: int,
    gpu_layers: int,
    memory_mapping_enabled: bool,
    cpu_headroom_ratio: float,
    gpu_mmap_headroom_ratio: float,
    gpu_no_mmap_headroom_ratio: float,
) -> None:
    """Require enough free host RAM before starting another model load.

    Vulkan/RADV model loads use substantial host-side staging memory in addition
    to VRAM. CPU inference and non-mmap GPU loads need much more host RAM than
    mmap'd GPU-offloaded models.
    """
    headroom_ratio = resolve_activation_headroom_ratio(
        gpu_layers=gpu_layers,
        memory_mapping_enabled=memory_mapping_enabled,
        cpu_headroom_ratio=cpu_headroom_ratio,
        gpu_mmap_headroom_ratio=gpu_mmap_headroom_ratio,
        gpu_no_mmap_headroom_ratio=gpu_no_mmap_headroom_ratio,
    )
    available_mb = int(psutil.virtual_memory().available / (1024 * 1024))
    estimated_need_mb = int(model_size_mb * headroom_ratio) if model_size_mb > 0 else 0
    required_mb = max(min_free_mb, estimated_need_mb)
    if available_mb < required_mb:
        raise InsufficientHostRamError(
            f"Insufficient host RAM: {available_mb} MB available, need at least {required_mb} MB "
            f"before loading another model"
        )


def assert_gtt_headroom_for_activation(
    *,
    stable_hardware_ids: list[str],
    memory_metrics: dict[str, dict],
    max_used_ratio: float,
) -> None:
    """Refuse activation when target GPUs show high GTT usage (VRAM spillover)."""
    if not stable_hardware_ids or max_used_ratio <= 0:
        return

    for stable_id in stable_hardware_ids:
        normalized = stable_id.strip()
        if not normalized:
            continue
        for hardware_id, metrics in memory_metrics.items():
            device_stable = metrics.get("stable_hardware_id", "")
            if device_stable != normalized and hardware_id != normalized:
                continue
            gtt_total = int(metrics.get("gtt_total_mb") or 0)
            gtt_used = int(metrics.get("gtt_used_mb") or 0)
            if gtt_total <= 0:
                continue
            used_ratio = gtt_used / gtt_total
            if used_ratio >= max_used_ratio:
                raise InsufficientGttError(
                    f"GPU {hardware_id} GTT usage {gtt_used}/{gtt_total} MB "
                    f"({used_ratio:.0%}) exceeds limit {max_used_ratio:.0%}; "
                    "unload other models before activating"
                )
