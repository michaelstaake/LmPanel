import copy
import threading
import time
from typing import Any, Callable

_CACHE_TTL_SECONDS = 10.0

_lock = threading.Lock()
_cached_payload: dict[str, Any] | None = None
_cached_at: float = 0.0


def get_cached_v1_models(build: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    global _cached_payload, _cached_at

    now = time.monotonic()
    with _lock:
        if _cached_payload is not None and (now - _cached_at) < _CACHE_TTL_SECONDS:
            return copy.deepcopy(_cached_payload)

    payload = build()

    with _lock:
        _cached_payload = copy.deepcopy(payload)
        _cached_at = time.monotonic()

    return payload


def invalidate_v1_models_cache() -> None:
    global _cached_payload, _cached_at

    with _lock:
        _cached_payload = None
        _cached_at = 0.0
