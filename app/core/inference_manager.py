import asyncio
import logging
import threading
import time
from collections.abc import AsyncIterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
import json

import httpx
import psutil

from app.core.config import get_settings
from app.core.model_activation import (
    assert_gtt_headroom_for_activation,
    assert_host_ram_for_activation,
    estimate_model_file_size_mb,
)
from app.core.pool_lifecycle import (
    DeactivateReason,
    FailureKind,
    LivenessKind,
    RuntimeStateKind,
    log_pool_event,
)
from app.models.device import Device
from app.models.model_config import ModelConfig

logger = logging.getLogger(__name__)

_pool_lock_registry_guard = threading.Lock()
_pool_lock_registry: dict[str, threading.Lock] = {}


def _lock_key_for_pool(pool_id: int) -> str:
    return f"pool:{pool_id}"


def _lock_key_for_device(stable_ids: list[str]) -> str:
    if not stable_ids:
        return "device:unknown"
    return "device:" + "|".join(sorted(stable_ids))


def _get_transition_lock(key: str) -> threading.Lock:
    with _pool_lock_registry_guard:
        lock = _pool_lock_registry.get(key)
        if lock is None:
            lock = threading.Lock()
            _pool_lock_registry[key] = lock
        return lock


@contextmanager
def _acquire_transition_lock(*keys: str):
    ordered = sorted({key for key in keys if key})
    acquired: list[threading.Lock] = []
    try:
        for key in ordered:
            lock = _get_transition_lock(key)
            lock.acquire()
            acquired.append(lock)
        yield
    finally:
        for lock in reversed(acquired):
            lock.release()


@dataclass
class PoolActivationTarget:
    """Represents a vendor-specific pool of GPUs to use together for a single model."""

    pool_id: int
    pool_name: str
    vendor: str
    devices: list[Device]
    split_mode: str = "layer"

    @property
    def runtime_vendor(self) -> str:
        return f"{self.vendor}_pool"

    @property
    def hardware_ids(self) -> list[str]:
        return [d.hardware_id for d in self.devices]

    @property
    def vram_ratios(self) -> list[int]:
        return [max(1, d.memory_mb) for d in self.devices]

    @property
    def combined_available_mb(self) -> int:
        return sum(max(0, d.memory_mb) for d in self.devices)


def _runtime_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        payload = None

    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()

    text = response.text.strip()
    if text:
        return text

    return f"Inference runtime request failed with status {response.status_code}"


@dataclass
class ModelRecoveryState:
    attempts: int
    next_attempt: float
    last_error: str | None = None
    failure_kind: str | None = None
    device_failure_kind: str | None = None


@dataclass
class RunningModel:
    model_id: int
    base_url: str
    device_id: int | None
    vendor: str
    pool_id: int | None = None
    pool_device_ids: list[int] = field(default_factory=list)
    stable_hardware_ids: list[str] = field(default_factory=list)


@dataclass
class LivenessResult:
    kind: LivenessKind
    detail: str | None = None


class InferenceManager:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._running: dict[int, RunningModel] = {}
        self._starting: set[int] = set()
        self._activation_lock = asyncio.Lock()
        self._recovery_state: dict[int, ModelRecoveryState] = {}
        self._device_healthy_streak: dict[str, int] = {}
        self._device_cooldown_required: set[str] = set()

    def mark_devices_need_cooldown(self, stable_hardware_ids: list[str]) -> None:
        for stable_id in stable_hardware_ids:
            normalized = stable_id.strip()
            if normalized:
                self._device_cooldown_required.add(normalized)
                self._device_healthy_streak[normalized] = 0

    def tick_device_health(self, memory_metrics: dict[str, dict]) -> None:
        """Increment healthy streak for GPUs with acceptable GTT; reset others."""
        max_ratio = self.settings.model_activation_max_gtt_used_ratio
        for metrics in memory_metrics.values():
            stable_id = (metrics.get("stable_hardware_id") or "").strip()
            if not stable_id:
                continue
            gtt_total = int(metrics.get("gtt_total_mb") or 0)
            gtt_used = int(metrics.get("gtt_used_mb") or 0)
            if gtt_total > 0 and (gtt_used / gtt_total) >= max_ratio:
                self._device_healthy_streak[stable_id] = 0
                continue
            self._device_healthy_streak[stable_id] = self._device_healthy_streak.get(stable_id, 0) + 1

    def device_cooldown_satisfied(self, stable_hardware_ids: list[str]) -> bool:
        required_ticks = max(1, self.settings.gpu_reset_cooldown_ticks)
        for stable_id in stable_hardware_ids:
            normalized = stable_id.strip()
            if not normalized or normalized not in self._device_cooldown_required:
                continue
            if self._device_healthy_streak.get(normalized, 0) < required_ticks:
                return False
        return True

    def clear_device_cooldown(self, stable_hardware_ids: list[str]) -> None:
        for stable_id in stable_hardware_ids:
            normalized = stable_id.strip()
            if normalized:
                self._device_cooldown_required.discard(normalized)

    def clear_recovery_state(self, model_id: int) -> None:
        self._recovery_state.pop(model_id, None)

    def record_recovery_failure(
        self,
        model_id: int,
        error: str,
        *,
        attempts: int,
        next_attempt: float,
        failure_kind: str | None = None,
        device_failure_kind: str | None = None,
    ) -> None:
        self._recovery_state[model_id] = ModelRecoveryState(
            attempts=attempts,
            next_attempt=next_attempt,
            last_error=error,
            failure_kind=failure_kind,
            device_failure_kind=device_failure_kind,
        )

    def note_recovery_error(self, model_id: int, error: str, *, failure_kind: str | None = None) -> None:
        state = self._recovery_state.get(model_id)
        if state is None:
            self._recovery_state[model_id] = ModelRecoveryState(
                attempts=0,
                next_attempt=0.0,
                last_error=error,
                failure_kind=failure_kind,
            )
        else:
            state.last_error = error
            if failure_kind is not None:
                state.failure_kind = failure_kind

    def get_recovery_state(self, model_id: int) -> ModelRecoveryState | None:
        return self._recovery_state.get(model_id)

    def pool_active_model_id(self, pool_id: int, *, exclude_model_id: int | None = None) -> int | None:
        for model_id, running in self._running.items():
            if exclude_model_id is not None and model_id == exclude_model_id:
                continue
            if running.pool_id == pool_id:
                return model_id
        return None

    async def resolve_runtime_state(self, model_id: int, *, activated: bool) -> dict[str, str | None]:
        if not activated:
            return {"runtime_state": RuntimeStateKind.DISABLED, "runtime_error": None}

        if model_id in self._starting:
            return {"runtime_state": RuntimeStateKind.STARTING, "runtime_error": None}

        if self.is_active(model_id):
            liveness = await self.classify_model_liveness(model_id)
            if liveness.kind == LivenessKind.PROCESS_DEAD:
                return {
                    "runtime_state": RuntimeStateKind.ERROR,
                    "runtime_error": liveness.detail or "Model process is not running",
                }
            if liveness.kind == LivenessKind.RUNTIME_UNREACHABLE:
                return {
                    "runtime_state": RuntimeStateKind.DEGRADED,
                    "runtime_error": liveness.detail,
                }
            return {"runtime_state": RuntimeStateKind.RUNNING, "runtime_error": None}

        state = self._recovery_state.get(model_id)
        max_attempts = self.settings.model_recovery_max_attempts
        if state is not None:
            if state.failure_kind == RuntimeStateKind.UNAVAILABLE:
                return {
                    "runtime_state": RuntimeStateKind.UNAVAILABLE,
                    "runtime_error": state.last_error,
                }
            if state.attempts >= max_attempts:
                return {
                    "runtime_state": RuntimeStateKind.BACKOFF_LIMITED,
                    "runtime_error": state.last_error,
                }

        return {
            "runtime_state": RuntimeStateKind.RECOVERING,
            "runtime_error": state.last_error if state else None,
        }

    def is_active(self, model_id: int) -> bool:
        return model_id in self._running

    async def classify_model_liveness(self, model_id: int) -> LivenessResult:
        running = self._running.get(model_id)
        if not running:
            return LivenessResult(LivenessKind.NOT_TRACKED, "Model is not registered as running")

        alive = await self.is_model_process_alive(model_id)
        if alive is False:
            failure_kind = await self._fetch_failure_kind(model_id)
            detail = "Model process is not running"
            if failure_kind == FailureKind.DEVICE_LOST:
                detail = "Model process died with GPU device_lost"
            return LivenessResult(LivenessKind.PROCESS_DEAD, detail)
        if alive is None:
            return LivenessResult(LivenessKind.RUNTIME_UNREACHABLE, "Inference runtime unreachable")

        return LivenessResult(LivenessKind.HEALTHY)

    async def is_model_process_alive(self, model_id: int) -> bool | None:
        """Return whether the model's runtime process is alive.

        ``None`` means "unknown" (runtime unreachable) — callers must NOT treat
        that as dead, otherwise a transient blip would trigger a needless restart.
        """
        running = self._running.get(model_id)
        if not running:
            return None
        url = f"{running.base_url}/runtime/models/{model_id}/alive"
        try:
            async with httpx.AsyncClient(timeout=self.settings.inference_service_timeout_seconds) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
        except Exception:
            return None
        if not data.get("tracked", True):
            return False
        return bool(data.get("alive"))

    async def _fetch_failure_kind(self, model_id: int) -> FailureKind | None:
        running = self._running.get(model_id)
        if not running:
            return None
        url = f"{running.base_url}/runtime/models/{model_id}/alive"
        try:
            async with httpx.AsyncClient(timeout=self.settings.inference_service_timeout_seconds) as client:
                response = await client.get(url)
                response.raise_for_status()
                raw = response.json().get("failure_kind")
        except Exception:
            return None
        if not raw:
            return None
        try:
            return FailureKind(raw)
        except ValueError:
            return FailureKind.GENERIC

    def runtime_url_for_vendor(self, vendor: str) -> str | None:
        effective_vendor = vendor.removesuffix("_pool")
        return self.settings.inference_runtime_url_for_vendor(effective_vendor)

    def has_runtime_for_vendor(self, vendor: str) -> bool:
        return self.runtime_url_for_vendor(vendor) is not None

    def _llama_http_timeout(self, *, for_stream: bool = False) -> httpx.Timeout:
        request_timeout = self.settings.llama_request_timeout_seconds
        read_timeout = (
            self.settings.llama_stream_stall_timeout_seconds
            if for_stream
            else request_timeout
        )
        connect_timeout = min(30, request_timeout)
        return httpx.Timeout(
            connect=connect_timeout,
            write=request_timeout,
            read=read_timeout,
            pool=request_timeout,
        )

    async def get_device_memory_mb(self) -> dict[str, dict]:
        """Fetch current memory metrics from all configured runtimes.

        Returns a mapping of hardware_id -> {"total_mb", "used_mb", "available_mb"}.
        Returns an empty dict if no runtimes are reachable.
        """
        result: dict[str, dict] = {}
        seen_urls: set[str] = set()
        runtime_map = self.settings.inference_runtime_url_map()
        timeout = self.settings.inference_service_timeout_seconds

        for base_url in runtime_map.values():
            if base_url in seen_urls:
                continue
            seen_urls.add(base_url)
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(f"{base_url}/runtime/status")
                    response.raise_for_status()
                data = response.json()
            except Exception:
                logger.warning("Failed to fetch runtime status from %s for device memory check", base_url)
                continue

            for device in data.get("devices", []):
                hardware_id = device.get("hardware_id")
                if not hardware_id:
                    continue
                total = int(device.get("memory_total_mb") or 0)
                used = int(device.get("memory_used_mb") or 0)
                result[hardware_id] = {
                    "total_mb": total,
                    "used_mb": used,
                    "available_mb": max(0, total - used),
                    "stable_hardware_id": device.get("stable_hardware_id") or "",
                    "gtt_total_mb": int(device.get("gtt_total_mb") or 0),
                    "gtt_used_mb": int(device.get("gtt_used_mb") or 0),
                }

        return result

    async def _fetch_memory_metrics_with_gtt(self) -> dict[str, dict]:
        return await self.get_device_memory_mb()

    def _assert_activation_guards(
        self,
        model: ModelConfig,
        *,
        stable_hardware_ids: list[str],
        memory_metrics: dict[str, dict] | None = None,
    ) -> None:
        self._assert_host_ram_for_model(model)
        if not stable_hardware_ids:
            return
        metrics = memory_metrics
        if metrics is None:
            return
        assert_gtt_headroom_for_activation(
            stable_hardware_ids=stable_hardware_ids,
            memory_metrics=metrics,
            max_used_ratio=self.settings.model_activation_max_gtt_used_ratio,
        )

    @staticmethod
    def _stable_hardware_ids_for_device(device: Device) -> list[str]:
        if device.stable_hardware_id and device.stable_hardware_id.strip():
            return [device.stable_hardware_id.strip()]
        return []

    @staticmethod
    def _stable_hardware_ids_for_pool(target: PoolActivationTarget) -> list[str]:
        return [
            device.stable_hardware_id.strip()
            for device in target.devices
            if device.stable_hardware_id and device.stable_hardware_id.strip()
        ]

    def _ensure_stable_hardware_available(self, stable_ids: list[str], *, exclude_model_id: int | None = None) -> None:
        if not stable_ids:
            return

        requested = set(stable_ids)
        for running_model_id, running in self._running.items():
            if exclude_model_id is not None and running_model_id == exclude_model_id:
                continue
            overlap = requested.intersection(running.stable_hardware_ids)
            if overlap:
                joined = ", ".join(sorted(overlap))
                raise RuntimeError(f"GPU already in use (stable id: {joined})")

    def _ensure_pool_available(self, pool_id: int, *, exclude_model_id: int | None = None) -> None:
        active_model_id = self.pool_active_model_id(pool_id, exclude_model_id=exclude_model_id)
        if active_model_id is not None:
            raise RuntimeError(
                f"GPU pool {pool_id} already has an active model (model_id={active_model_id}); "
                "only one pooled model may run at a time"
            )

    def _assert_host_ram_for_model(self, model: ModelConfig) -> None:
        assert_host_ram_for_activation(
            model_size_mb=estimate_model_file_size_mb(model),
            min_free_mb=self.settings.model_activation_min_free_ram_mb,
            gpu_layers=model.gpu_layers,
            memory_mapping_enabled=model.memory_mapping_enabled,
            cpu_headroom_ratio=self.settings.model_activation_ram_headroom_ratio,
            gpu_mmap_headroom_ratio=self.settings.model_activation_gpu_offload_headroom_ratio,
            gpu_no_mmap_headroom_ratio=self.settings.model_activation_gpu_no_mmap_headroom_ratio,
        )

    def _health_timeout_for_vendor(self, vendor: str) -> int:
        if vendor.endswith("_pool"):
            return max(
                self.settings.llama_startup_timeout_seconds,
                self.settings.pool_startup_timeout_seconds,
            )
        return self.settings.llama_startup_timeout_seconds

    async def activate_model(self, model: ModelConfig, device: Device) -> None:
        stable_ids = self._stable_hardware_ids_for_device(device)
        lock_keys = (_lock_key_for_device(stable_ids),)

        async with self._activation_lock:
            with _acquire_transition_lock(*lock_keys):
                if model.id in self._running:
                    return

                self._ensure_stable_hardware_available(stable_ids, exclude_model_id=model.id)

                runtime_url = self.runtime_url_for_vendor(device.vendor)
                if not runtime_url:
                    raise RuntimeError(f"No inference runtime configured for device vendor: {device.vendor}")

                memory_metrics = await self._fetch_memory_metrics_with_gtt()
                self._assert_activation_guards(
                    model,
                    stable_hardware_ids=stable_ids,
                    memory_metrics=memory_metrics,
                )

                payload = {
                    "model_id": model.id,
                    "alias": model.alias,
                    "file_path": model.file_path,
                    "mmproj_path": _resolve_mmproj_path(model),
                    "context_length": model.context_length,
                    "threads": model.threads,
                    "gpu_layers": model.gpu_layers,
                    "flash_attention_enabled": model.flash_attention_enabled,
                    "cache_type_k": model.cache_type_k,
                    "cache_type_v": model.cache_type_v,
                    "batch_size": model.batch_size,
                    "ubatch_size": model.ubatch_size,
                    "memory_mapping_enabled": model.memory_mapping_enabled,
                    "vendor": device.vendor,
                    "hardware_id": device.hardware_id,
                    "stable_hardware_id": device.stable_hardware_id,
                    "stable_hardware_ids": stable_ids,
                    "discourage_thinking": model.discourage_thinking,
                }
                timeout = self.settings.inference_service_timeout_seconds
                started = time.monotonic()
                self._starting.add(model.id)
                try:
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        response = await client.post(f"{runtime_url}/runtime/models/activate", json=payload)
                        if response.is_error:
                            raise RuntimeError(_runtime_error_detail(response))

                    self._running[model.id] = RunningModel(
                        model_id=model.id,
                        base_url=runtime_url,
                        device_id=device.id,
                        vendor=device.vendor,
                        stable_hardware_ids=stable_ids,
                    )

                    ok = await self.wait_until_healthy(model.id)
                    if not ok:
                        await self.deactivate_model(model.id, reason=DeactivateReason.ACTIVATION_ROLLBACK)
                        raise RuntimeError(f"Model {model.alias} failed health check")
                finally:
                    self._starting.discard(model.id)

                log_pool_event(
                    "activate.success",
                    model_id=model.id,
                    vendor=device.vendor,
                    hardware_id=device.hardware_id,
                    startup_duration_ms=int((time.monotonic() - started) * 1000),
                )
                self.clear_recovery_state(model.id)

    async def activate_model_on_pool(self, model: ModelConfig, target: PoolActivationTarget) -> None:
        try:
            await self._activate_model_on_pool_once(model, target)
        except Exception as exc:
            if (
                self.settings.pool_tensor_split_fallback
                and target.split_mode == "tensor"
            ):
                layer_target = PoolActivationTarget(
                    pool_id=target.pool_id,
                    pool_name=target.pool_name,
                    vendor=target.vendor,
                    devices=target.devices,
                    split_mode="layer",
                )
                log_pool_event(
                    "tensor_fallback",
                    model_id=model.id,
                    pool_id=target.pool_id,
                    original_error=str(exc),
                )
                logger.warning(
                    "Tensor split activation failed for model %s; retrying with layer split: %s",
                    model.alias,
                    exc,
                )
                await self._activate_model_on_pool_once(model, layer_target)
                return
            raise

    async def _activate_model_on_pool_once(self, model: ModelConfig, target: PoolActivationTarget) -> None:
        stable_ids = self._stable_hardware_ids_for_pool(target)
        lock_keys = (_lock_key_for_pool(target.pool_id), _lock_key_for_device(stable_ids))

        async with self._activation_lock:
            with _acquire_transition_lock(*lock_keys):
                if model.id in self._running:
                    return

                self._ensure_pool_available(target.pool_id, exclude_model_id=model.id)
                self._ensure_stable_hardware_available(stable_ids, exclude_model_id=model.id)

                runtime_url = self.runtime_url_for_vendor(target.runtime_vendor)
                if not runtime_url:
                    raise RuntimeError(f"No inference runtime configured for {target.vendor} (required for GPU pool)")

                memory_metrics = await self._fetch_memory_metrics_with_gtt()
                self._assert_activation_guards(
                    model,
                    stable_hardware_ids=stable_ids,
                    memory_metrics=memory_metrics,
                )

                aligned_stable_ids = [(device.stable_hardware_id or "").strip() for device in target.devices]

                payload = {
                    "model_id": model.id,
                    "alias": model.alias,
                    "file_path": model.file_path,
                    "mmproj_path": _resolve_mmproj_path(model),
                    "context_length": model.context_length,
                    "threads": model.threads,
                    "gpu_layers": model.gpu_layers,
                    "flash_attention_enabled": model.flash_attention_enabled,
                    "cache_type_k": model.cache_type_k,
                    "cache_type_v": model.cache_type_v,
                    "batch_size": model.batch_size,
                    "ubatch_size": model.ubatch_size,
                    "memory_mapping_enabled": model.memory_mapping_enabled,
                    "vendor": target.runtime_vendor,
                    "hardware_id": target.hardware_ids[0],
                    "hardware_ids": target.hardware_ids,
                    "vram_ratios": target.vram_ratios,
                    "split_mode": target.split_mode,
                    "stable_hardware_ids": aligned_stable_ids,
                    "discourage_thinking": model.discourage_thinking,
                }
                timeout = self.settings.inference_service_timeout_seconds
                started = time.monotonic()
                log_pool_event(
                    "activate.start",
                    model_id=model.id,
                    pool_id=target.pool_id,
                    pool_name=target.pool_name,
                    split_mode=target.split_mode,
                    vram_ratios=",".join(str(r) for r in target.vram_ratios),
                    stable_bdfs=",".join(stable_ids),
                )
                self._starting.add(model.id)
                try:
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        response = await client.post(f"{runtime_url}/runtime/models/activate", json=payload)
                        if response.is_error:
                            raise RuntimeError(_runtime_error_detail(response))

                    self._running[model.id] = RunningModel(
                        model_id=model.id,
                        base_url=runtime_url,
                        device_id=None,
                        vendor=target.runtime_vendor,
                        pool_id=target.pool_id,
                        pool_device_ids=[d.id for d in target.devices],
                        stable_hardware_ids=stable_ids,
                    )

                    ok = await self.wait_until_healthy(model.id)
                    if not ok:
                        await self.deactivate_model(model.id, reason=DeactivateReason.ACTIVATION_ROLLBACK)
                        raise RuntimeError(f"Model {model.alias} failed health check on GPU pool")
                finally:
                    self._starting.discard(model.id)

                log_pool_event(
                    "activate.success",
                    model_id=model.id,
                    pool_id=target.pool_id,
                    split_mode=target.split_mode,
                    startup_duration_ms=int((time.monotonic() - started) * 1000),
                )
                self.clear_recovery_state(model.id)

    async def deactivate_model(self, model_id: int, *, reason: DeactivateReason | str = DeactivateReason.USER) -> None:
        running = self._running.get(model_id)
        if not running:
            return

        lock_keys: list[str] = []
        if running.pool_id is not None:
            lock_keys.append(_lock_key_for_pool(running.pool_id))
        if running.stable_hardware_ids:
            lock_keys.append(_lock_key_for_device(running.stable_hardware_ids))

        async with self._activation_lock:
            with _acquire_transition_lock(*lock_keys):
                running = self._running.pop(model_id, None)
                if not running:
                    return
                log_pool_event(
                    "deactivate",
                    model_id=model_id,
                    pool_id=running.pool_id,
                    vendor=running.vendor,
                    reason=str(reason),
                )
                try:
                    await asyncio.to_thread(self._deactivate_remote, running, model_id)
                except Exception:
                    logger.exception("Failed to deactivate remote model %s", model_id)
                    await asyncio.to_thread(self._force_kill_remote_model, running, model_id)

    def deactivate_model_sync(self, model_id: int, *, reason: DeactivateReason | str = DeactivateReason.USER) -> None:
        running = self._running.get(model_id)
        if not running:
            return

        lock_keys: list[str] = []
        if running.pool_id is not None:
            lock_keys.append(_lock_key_for_pool(running.pool_id))
        if running.stable_hardware_ids:
            lock_keys.append(_lock_key_for_device(running.stable_hardware_ids))

        with _acquire_transition_lock(*lock_keys):
            running = self._running.pop(model_id, None)
            if not running:
                return
            log_pool_event(
                "deactivate",
                model_id=model_id,
                pool_id=running.pool_id,
                vendor=running.vendor,
                reason=str(reason),
            )
            try:
                self._deactivate_remote(running, model_id)
            except Exception:
                logger.exception("Failed to deactivate remote model %s", model_id)
                self._force_kill_remote_model(running, model_id)

    def _deactivate_remote(self, running: RunningModel, model_id: int) -> None:
        with httpx.Client(timeout=self.settings.inference_service_timeout_seconds) as client:
            client.post(f"{running.base_url}/runtime/models/{model_id}/deactivate").raise_for_status()

    def _force_kill_remote_model(self, running: RunningModel, model_id: int) -> None:
        try:
            with httpx.Client(timeout=self.settings.inference_service_timeout_seconds) as client:
                response = client.get(f"{running.base_url}/runtime/models/{model_id}/alive")
                response.raise_for_status()
                pid = response.json().get("pid")
            if pid:
                psutil.Process(int(pid)).kill()
                logger.warning("Force-killed orphaned llama-server process %s for model %s", pid, model_id)
        except Exception:
            logger.exception("Failed to force-kill remote model %s process", model_id)

    async def wait_until_healthy(self, model_id: int) -> bool:
        running = self._running.get(model_id)
        if not running:
            return False

        url = f"{running.base_url}/runtime/models/{model_id}/health"
        timeout = self.settings.llama_health_timeout_seconds
        startup_timeout = self._health_timeout_for_vendor(running.vendor)
        deadline = time.monotonic() + max(timeout, startup_timeout)

        while time.monotonic() < deadline:
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(url)
                if response.status_code == 200:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)

        return False

    async def chat_completion(self, model_id: int, payload: dict, *, request_timeout: int | None = None) -> dict:
        running = self._running.get(model_id)
        if not running:
            raise RuntimeError("Model is not active")

        url = f"{running.base_url}/runtime/models/{model_id}/chat/completions"
        if request_timeout is None and running.vendor.endswith("_pool"):
            request_timeout = max(
                self.settings.inference_service_timeout_seconds,
                self.settings.pool_startup_timeout_seconds,
            )
        timeout = request_timeout if request_timeout is not None else self.settings.inference_service_timeout_seconds
        async with httpx.AsyncClient(timeout=self._llama_http_timeout(for_stream=False)) as client:
            response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    async def stream_chat_completion(self, model_id: int, payload: dict, *, request_timeout: int | None = None) -> AsyncIterator[bytes]:
        running = self._running.get(model_id)
        if not running:
            raise RuntimeError("Model is not active")

        url = f"{running.base_url}/runtime/models/{model_id}/chat/completions"
        if request_timeout is None and running.vendor.endswith("_pool"):
            request_timeout = max(
                self.settings.llama_request_timeout_seconds,
                self.settings.pool_startup_timeout_seconds,
            )
        timeout = request_timeout if request_timeout is not None else self.settings.llama_request_timeout_seconds
        try:
            async with httpx.AsyncClient(timeout=self._llama_http_timeout(for_stream=True)) as client:
                async with client.stream("POST", url, json=payload) as response:
                    if response.is_error:
                        await response.aread()
                        raise RuntimeError(_runtime_error_detail(response))

                    async for chunk in response.aiter_bytes():
                        if chunk:
                            yield chunk
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Inference stream error: {exc}") from exc


def _resolve_mmproj_path(model: ModelConfig) -> str | None:
    if not model.vision_enabled or not model.mmproj_file_name:
        return None
    return str(Path(model.file_path).resolve().parent / model.mmproj_file_name)
