"""Structured logging and enums for GPU pool lifecycle transitions."""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

logger = logging.getLogger("pool.lifecycle")


class DeactivateReason(StrEnum):
    USER = "user"
    HEALTH_TIMEOUT = "health_timeout"
    WATCHDOG_LIVENESS = "watchdog_liveness"
    POOL_CLEANUP = "pool_cleanup"
    POOL_SUSPEND = "pool_suspend"
    CHAT_FAILURE = "chat_failure"
    ACTIVATION_ROLLBACK = "activation_rollback"
    DEVICE_DISABLED = "device_disabled"
    SHUTDOWN = "shutdown"


class LivenessKind(StrEnum):
    HEALTHY = "healthy"
    PROCESS_DEAD = "process_dead"
    RUNTIME_UNREACHABLE = "runtime_unreachable"
    NOT_TRACKED = "not_tracked"
    SLOW_STARTUP = "slow_startup"


class RuntimeStateKind(StrEnum):
    DISABLED = "disabled"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    WEDGED = "wedged"
    UNAVAILABLE = "unavailable"
    RECOVERING = "recovering"
    BACKOFF_LIMITED = "backoff_limited"
    ERROR = "error"


def log_pool_event(event: str, **fields: Any) -> None:
    """Emit a structured pool lifecycle log line."""
    parts = [f"{key}={value}" for key, value in sorted(fields.items()) if value is not None]
    message = f"pool.{event}"
    if parts:
        message = f"{message} {' '.join(parts)}"
    logger.info(message)
