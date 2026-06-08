from __future__ import annotations

import logging
import re
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_GPU_OFFLOAD_VENDORS = frozenset({"nvidia", "vulkan", "rocm"})


def format_gpu_layers_for_cli(gpu_layers: int) -> str:
    if gpu_layers <= -1:
        return "all"
    return str(max(0, gpu_layers))


def llama_offload_extra_args(vendor: str, gpu_layers: int, *, fit_to_vram: bool) -> list[str]:
    effective_vendor = vendor.removesuffix("_pool")
    if effective_vendor not in _GPU_OFFLOAD_VENDORS or gpu_layers == 0:
        return []

    args: list[str] = []
    if not fit_to_vram:
        args.extend(["--fit", "off"])
    if not vendor.endswith("_pool"):
        args.extend(["--main-gpu", "0"])
    return args


def apply_rocm_runtime_env(env: dict[str, str]) -> None:
    override = get_settings().rocm_hsa_override_gfx_version.strip()
    if override:
        env["HSA_OVERRIDE_GFX_VERSION"] = override


def rocm_pool_stability_args() -> list[str]:
    settings = get_settings()
    args: list[str] = []

    parallel = max(1, settings.rocm_pool_parallel)
    args.extend(["--parallel", str(parallel)])

    cache_ram_mb = max(0, settings.rocm_pool_cache_ram_mb)
    args.extend(["--cache-ram", str(cache_ram_mb)])

    return args


def rocm_pool_flash_attn_enabled(requested: bool) -> bool:
    settings = get_settings()
    if settings.rocm_pool_flash_attn_enabled:
        return requested
    return False


def resolve_flash_attn_for_launch(vendor: str, requested: bool, split_mode: str) -> bool:
    if vendor != "rocm_pool":
        return requested

    enabled = rocm_pool_flash_attn_enabled(requested)
    normalized_split_mode = split_mode.strip().lower()

    if normalized_split_mode == "tensor" and not enabled:
        settings = get_settings()
        if settings.rocm_pool_allow_tensor_split and settings.rocm_pool_flash_attn_enabled:
            logger.warning(
                "Ignoring model flash-attn setting for ROCm tensor pool; forcing --flash-attn on"
            )
            return True

    return enabled


def effective_pool_split_mode(vendor: str, split_mode: str, *, flash_attn_enabled: bool) -> str:
    if vendor != "rocm_pool":
        return split_mode

    normalized = split_mode.strip().lower()
    if normalized not in {"layer", "tensor"}:
        logger.warning("ROCm pool requested unsupported split mode '%s'; using 'layer'", split_mode)
        return "layer"

    if normalized != "tensor":
        return normalized

    if not flash_attn_enabled:
        logger.warning("ROCm pool requested split mode 'tensor' but flash-attn is off; using 'layer' instead")
        return "layer"

    settings = get_settings()
    if settings.rocm_pool_allow_tensor_split:
        return normalized

    logger.warning(
        "ROCm pool requested split mode 'tensor' but it is disabled by configuration; using 'layer' instead"
    )
    return "layer"


def validate_gpu_offload_from_log(log_path: str, vendor: str, gpu_layers: int) -> None:
    effective_vendor = vendor.removesuffix("_pool")
    if effective_vendor not in _GPU_OFFLOAD_VENDORS or gpu_layers == 0:
        return

    try:
        text = Path(log_path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        logger.warning("Could not read llama log at %s for GPU offload verification", log_path)
        return

    lowered = text.lower()
    if "no usable gpu found" in lowered or "gpu-layers option will be ignored" in lowered:
        raise RuntimeError(
            "llama-server has no usable GPU backend. Rebuild with the correct inference profile "
            "(for AMD: docker compose --profile rocm) and verify AMDGPU_TARGETS matches your GPU."
        )

    match = re.search(r"offloaded\s+(\d+)/(\d+)\s+layers", text, re.IGNORECASE)
    if match and int(match.group(1)) == 0 and int(match.group(2)) > 0:
        raise RuntimeError(
            "Model loaded with 0 GPU layers (CPU-only). Lower context length, keep GPU layers at 99 (all layers, or -1 for legacy), "
            "set LLAMA_FIT_TO_VRAM=false, and confirm ROCm sees the GPU inside the inference-rocm container."
        )
