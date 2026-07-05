"""Helpers for choosing single-GPU vs pooled inference targets."""

from __future__ import annotations

from app.core.inference_manager import PoolActivationTarget
from app.models.device import Device


def best_fitting_pool_member(
    target: PoolActivationTarget,
    model_size_mb: int,
    memory_metrics: dict,
) -> Device | None:
    """Return the pool member with the most free VRAM that can hold the model alone."""
    if model_size_mb <= 0:
        return None

    fitting: list[tuple[Device, int]] = []
    for device in target.devices:
        metrics = memory_metrics.get(device.hardware_id, {})
        total_mb = metrics.get("total_mb", 0)
        available_mb = metrics.get("available_mb", 0)
        if total_mb > 0 and available_mb >= model_size_mb:
            fitting.append((device, available_mb))

    if not fitting:
        return None

    fitting.sort(key=lambda item: item[1], reverse=True)
    return fitting[0][0]


def resolve_fitting_gpu(
    gpu_candidates: list[Device],
    model_size_mb: int,
    memory_metrics: dict,
) -> Device | None:
    """Pick the best single GPU that can run the model."""
    if not gpu_candidates:
        return None

    if model_size_mb > 0 and memory_metrics:
        fitting: list[tuple[Device, int]] = []
        unknown: list[Device] = []
        for gpu in gpu_candidates:
            metrics = memory_metrics.get(gpu.hardware_id, {})
            total_mb = metrics.get("total_mb", 0)
            available_mb = metrics.get("available_mb", 0)
            if total_mb == 0:
                unknown.append(gpu)
            elif available_mb >= model_size_mb:
                fitting.append((gpu, available_mb))

        if fitting:
            fitting.sort(key=lambda item: item[1], reverse=True)
            return fitting[0][0]
        if unknown:
            unknown.sort(key=lambda gpu: (gpu.priority, gpu.id))
            return unknown[0]
        return None

    return sorted(gpu_candidates, key=lambda gpu: (gpu.priority, gpu.id))[0]


def pick_best_pool_candidate(
    pool_candidates: list[tuple[PoolActivationTarget, int]],
) -> PoolActivationTarget | None:
    if not pool_candidates:
        return None

    pool_candidates.sort(
        key=lambda item: (
            min(device.priority for device in item[0].devices),
            -item[1],
            item[0].pool_id,
        )
    )
    return pool_candidates[0][0]
