"""VRAM need estimation for model activation preflight."""

from __future__ import annotations

_KV_TYPE_MULTIPLIERS: dict[str, float] = {
    "f32": 2.0,
    "f16": 1.0,
    "bf16": 1.0,
    "q8_0": 0.5,
    "q8_1": 0.5,
    "q4_0": 0.25,
    "q4_1": 0.25,
    "iq4_nl": 0.25,
    "q4_k": 0.25,
}


def kv_cache_size_multiplier(cache_type_k: str | None, cache_type_v: str | None) -> float:
    """Scale the KV heuristic when cache types are quantized."""
    default = 0.5  # recent llama.cpp defaults; conservative vs fp16
    k_key = (cache_type_k or "").strip().lower()
    v_key = (cache_type_v or cache_type_k or "").strip().lower()
    k_mult = _KV_TYPE_MULTIPLIERS.get(k_key, default if not k_key else 1.0)
    v_mult = _KV_TYPE_MULTIPLIERS.get(v_key, default if not v_key else 1.0)
    return (k_mult + v_mult) / 2.0


def estimate_activation_vram_mb(
    *,
    model_size_mb: int,
    context_length: int,
    gpu_layers: int,
    kv_mb_per_1k_tokens: float,
    compute_margin_mb: int,
    headroom_mb: int,
    vram_share: float = 1.0,
    cache_type_k: str | None = None,
    cache_type_v: str | None = None,
) -> int:
    """Estimate VRAM required for a model launch on one GPU.

    ``vram_share`` is the fraction of weights/KV assigned to this GPU (1.0 for
    single-GPU; proportional to tensor-split ratio for pool members).
    """
    if gpu_layers == 0 or model_size_mb <= 0:
        return 0

    share = max(0.0, min(1.0, vram_share))
    weights_mb = int(model_size_mb * share)
    kv_scale = kv_cache_size_multiplier(cache_type_k, cache_type_v)
    kv_mb = int((max(0, context_length) / 1000.0) * kv_mb_per_1k_tokens * kv_scale * share)
    margin_mb = int((compute_margin_mb + headroom_mb) * share)
    return weights_mb + kv_mb + margin_mb


def pool_member_vram_share(member_ratio: int, total_ratio: int) -> float:
    if total_ratio <= 0:
        return 1.0
    return max(0.0, member_ratio) / total_ratio
