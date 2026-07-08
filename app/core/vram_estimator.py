"""VRAM need estimation for model activation preflight."""

from __future__ import annotations


def estimate_activation_vram_mb(
    *,
    model_size_mb: int,
    context_length: int,
    gpu_layers: int,
    kv_mb_per_1k_tokens: float,
    compute_margin_mb: int,
    headroom_mb: int,
    vram_share: float = 1.0,
) -> int:
    """Estimate VRAM required for a model launch on one GPU.

    ``vram_share`` is the fraction of weights/KV assigned to this GPU (1.0 for
    single-GPU; proportional to tensor-split ratio for pool members).
    """
    if gpu_layers == 0 or model_size_mb <= 0:
        return 0

    share = max(0.0, min(1.0, vram_share))
    weights_mb = int(model_size_mb * share)
    kv_mb = int((max(0, context_length) / 1000.0) * kv_mb_per_1k_tokens * share)
    margin_mb = int(compute_margin_mb * share) + headroom_mb
    return weights_mb + kv_mb + margin_mb


def pool_member_vram_share(member_ratio: int, total_ratio: int) -> float:
    if total_ratio <= 0:
        return 1.0
    return max(0.0, member_ratio) / total_ratio
