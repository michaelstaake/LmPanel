from __future__ import annotations

from app.inference.backends.anpu_flm import AnpuFlmBackend
from app.inference.backends.base import InferenceBackend, LaunchPlan
from app.inference.backends.llama_cpp import LlamaCppBackend

_llama_backend = LlamaCppBackend()
_anpu_backend = AnpuFlmBackend()


def select_backend(vendor: str) -> InferenceBackend:
    effective_vendor = vendor.removesuffix("_pool")
    if effective_vendor == "anpu":
        return _anpu_backend
    return _llama_backend


__all__ = [
    "AnpuFlmBackend",
    "InferenceBackend",
    "LaunchPlan",
    "LlamaCppBackend",
    "select_backend",
]
