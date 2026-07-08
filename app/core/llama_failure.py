"""Classify llama-server log output for recovery decisions."""

from __future__ import annotations

import re

from app.core.pool_lifecycle import FailureKind

_DEVICE_LOST_PATTERNS = (
    re.compile(r"VK_ERROR_DEVICE_LOST", re.IGNORECASE),
    re.compile(r"ErrorOutOfDeviceMemory", re.IGNORECASE),
    re.compile(r"ggml_vulkan:.*failed", re.IGNORECASE),
    re.compile(r"device.?lost", re.IGNORECASE),
    re.compile(r"VK_ERROR_OUT_OF_DEVICE_MEMORY", re.IGNORECASE),
)

_TENSOR_UNSUPPORTED_PATTERNS = (
    re.compile(r"split.?mode.*tensor.*not.*support", re.IGNORECASE),
    re.compile(r"tensor.*split.*not.*support", re.IGNORECASE),
    re.compile(r"unsupported.*split.?mode", re.IGNORECASE),
)


def classify_llama_log(text: str) -> FailureKind:
    if not text:
        return FailureKind.GENERIC
    for pattern in _DEVICE_LOST_PATTERNS:
        if pattern.search(text):
            return FailureKind.DEVICE_LOST
    return FailureKind.GENERIC


def log_indicates_tensor_split_unsupported(text: str) -> bool:
    if not text:
        return False
    return any(pattern.search(text) for pattern in _TENSOR_UNSUPPORTED_PATTERNS)


def read_log_tail(log_path: str, *, max_bytes: int = 65536) -> str:
    try:
        with open(log_path, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            return handle.read().decode("utf-8", errors="ignore")
    except OSError:
        return ""
