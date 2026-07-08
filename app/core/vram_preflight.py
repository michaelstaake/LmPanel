"""VRAM preflight checks for model activation."""

from __future__ import annotations

from app.core.config import Settings
from app.core.inference_manager import PoolActivationTarget
from app.core.model_activation import InsufficientVramError, estimate_model_file_size_mb
from app.core.vram_estimator import estimate_activation_vram_mb, pool_member_vram_share
from app.models.device import Device
from app.models.model_config import ModelConfig


def estimate_model_vram_need_mb(model: ModelConfig, settings: Settings, *, vram_share: float = 1.0) -> int:
    return estimate_activation_vram_mb(
        model_size_mb=estimate_model_file_size_mb(model),
        context_length=model.context_length,
        gpu_layers=model.gpu_layers,
        kv_mb_per_1k_tokens=settings.vram_kv_mb_per_1k_tokens,
        compute_margin_mb=settings.vram_compute_margin_mb,
        headroom_mb=settings.vram_headroom_mb,
        vram_share=vram_share,
    )


def assert_device_vram_available(
    *,
    device: Device,
    required_mb: int,
    memory_metrics: dict[str, dict],
) -> None:
    if required_mb <= 0:
        return
    metrics = memory_metrics.get(device.hardware_id, {})
    total_mb = int(metrics.get("total_mb") or 0)
    available_mb = int(metrics.get("available_mb") or 0)
    if total_mb <= 0:
        return
    if available_mb < required_mb:
        shortfall = required_mb - available_mb
        raise InsufficientVramError(
            f"GPU {device.name} ({device.hardware_id}) needs ~{required_mb} MB "
            f"but only {available_mb} MB available (short by {shortfall} MB)"
        )


def assert_pool_members_vram_available(
    *,
    model: ModelConfig,
    target: PoolActivationTarget,
    memory_metrics: dict[str, dict],
    settings: Settings,
) -> None:
    if model.gpu_layers == 0:
        return

    total_ratio = sum(max(1, device.memory_mb) for device in target.devices)
    for index, device in enumerate(target.devices):
        member_ratio = max(1, device.memory_mb)
        share = pool_member_vram_share(member_ratio, total_ratio)
        required_mb = estimate_model_vram_need_mb(model, settings, vram_share=share)
        try:
            assert_device_vram_available(
                device=device,
                required_mb=required_mb,
                memory_metrics=memory_metrics,
            )
        except InsufficientVramError as exc:
            raise InsufficientVramError(
                f"Pool member {index + 1}/{len(target.devices)}: {exc}"
            ) from exc

    combined_required = estimate_model_vram_need_mb(model, settings, vram_share=1.0)
    combined_available = sum(
        int(memory_metrics.get(device.hardware_id, {}).get("available_mb") or 0)
        for device in target.devices
    )
    totals_verified = all(
        int(memory_metrics.get(device.hardware_id, {}).get("total_mb") or 0) > 0
        for device in target.devices
    )
    if totals_verified and combined_available < combined_required:
        raise InsufficientVramError(
            f"Model needs ~{combined_required} MB VRAM across pool but only "
            f"{combined_available} MB combined available"
        )
