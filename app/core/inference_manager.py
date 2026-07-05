import asyncio
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
import json
from collections.abc import AsyncIterator

import httpx
import psutil

from app.core.config import get_settings
from app.core.model_activation import assert_host_ram_for_activation, estimate_model_file_size_mb
from app.models.device import Device
from app.models.model_config import ModelConfig

logger = logging.getLogger(__name__)


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


@dataclass
class RunningModel:
    model_id: int
    base_url: str
    device_id: int | None
    vendor: str
    pool_device_ids: list[int] = field(default_factory=list)
    stable_hardware_ids: list[str] = field(default_factory=list)


class InferenceManager:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._running: dict[int, RunningModel] = {}
        self._activation_lock = asyncio.Lock()
        self._recovery_state: dict[int, ModelRecoveryState] = {}

    def clear_recovery_state(self, model_id: int) -> None:
        self._recovery_state.pop(model_id, None)

    def record_recovery_failure(self, model_id: int, error: str, *, attempts: int, next_attempt: float) -> None:
        self._recovery_state[model_id] = ModelRecoveryState(
            attempts=attempts,
            next_attempt=next_attempt,
            last_error=error,
        )

    def note_recovery_error(self, model_id: int, error: str) -> None:
        state = self._recovery_state.get(model_id)
        if state is None:
            self._recovery_state[model_id] = ModelRecoveryState(attempts=0, next_attempt=0.0, last_error=error)
        else:
            state.last_error = error

    def get_recovery_state(self, model_id: int) -> ModelRecoveryState | None:
        return self._recovery_state.get(model_id)

    async def resolve_runtime_state(self, model_id: int, *, activated: bool) -> dict[str, str | None]:
        if not activated:
            return {"runtime_state": "disabled", "runtime_error": None}

        if self.is_active(model_id):
            alive = await self.is_model_process_alive(model_id)
            if alive is False:
                return {"runtime_state": "error", "runtime_error": "Model process is not running"}
            return {"runtime_state": "running", "runtime_error": None}

        state = self._recovery_state.get(model_id)
        max_attempts = self.settings.model_recovery_max_attempts
        if state is not None and state.attempts >= max_attempts:
            return {"runtime_state": "error", "runtime_error": state.last_error}

        return {
            "runtime_state": "recovering",
            "runtime_error": state.last_error if state else None,
        }

    def is_active(self, model_id: int) -> bool:
        return model_id in self._running

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

    def runtime_url_for_vendor(self, vendor: str) -> str | None:
        effective_vendor = vendor.removesuffix("_pool")
        return self.settings.inference_runtime_url_for_vendor(effective_vendor)

    def has_runtime_for_vendor(self, vendor: str) -> bool:
        return self.runtime_url_for_vendor(vendor) is not None

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
                }

        return result

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

    async def activate_model(self, model: ModelConfig, device: Device) -> None:
        async with self._activation_lock:
            if model.id in self._running:
                return

            stable_ids = self._stable_hardware_ids_for_device(device)
            self._ensure_stable_hardware_available(stable_ids, exclude_model_id=model.id)

            runtime_url = self.runtime_url_for_vendor(device.vendor)
            if not runtime_url:
                raise RuntimeError(f"No inference runtime configured for device vendor: {device.vendor}")

            self._assert_host_ram_for_model(model)

            payload = {
                "model_id": model.id,
                "alias": model.alias,
                "file_path": model.file_path,
                "mmproj_path": _resolve_mmproj_path(model),
                "context_length": model.context_length,
                "threads": model.threads,
                "gpu_layers": model.gpu_layers,
                "flash_attention_enabled": model.flash_attention_enabled,
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
                self.deactivate_model(model.id)
                raise RuntimeError(f"Model {model.alias} failed health check")

            self.clear_recovery_state(model.id)

    async def activate_model_on_pool(self, model: ModelConfig, target: PoolActivationTarget) -> None:
        async with self._activation_lock:
            if model.id in self._running:
                return

            stable_ids = self._stable_hardware_ids_for_pool(target)
            self._ensure_stable_hardware_available(stable_ids, exclude_model_id=model.id)

            runtime_url = self.runtime_url_for_vendor(target.runtime_vendor)
            if not runtime_url:
                raise RuntimeError(f"No inference runtime configured for {target.vendor} (required for GPU pool)")

            self._assert_host_ram_for_model(model)

            # Send PCI BDFs aligned 1:1 with hardware_ids (empty where unknown) so the
            # runtime can re-resolve each pool member's live Vulkan index from its
            # stable address at launch time.
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
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(f"{runtime_url}/runtime/models/activate", json=payload)
                if response.is_error:
                    raise RuntimeError(_runtime_error_detail(response))

            self._running[model.id] = RunningModel(
                model_id=model.id,
                base_url=runtime_url,
                device_id=None,
                vendor=target.runtime_vendor,
                pool_device_ids=[d.id for d in target.devices],
                stable_hardware_ids=stable_ids,
            )

            ok = await self.wait_until_healthy(model.id)
            if not ok:
                self.deactivate_model(model.id)
                raise RuntimeError(f"Model {model.alias} failed health check on GPU pool")

            self.clear_recovery_state(model.id)

    def deactivate_model(self, model_id: int) -> None:
        running = self._running.pop(model_id, None)
        if not running:
            return
        try:
            with httpx.Client(timeout=self.settings.inference_service_timeout_seconds) as client:
                client.post(f"{running.base_url}/runtime/models/{model_id}/deactivate").raise_for_status()
        except Exception:
            logger.exception("Failed to deactivate remote model %s", model_id)
            self._force_kill_remote_model(running, model_id)

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
        deadline = time.monotonic() + max(timeout, self.settings.llama_startup_timeout_seconds)

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
        timeout = request_timeout if request_timeout is not None else self.settings.inference_service_timeout_seconds
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    async def stream_chat_completion(self, model_id: int, payload: dict, *, request_timeout: int | None = None) -> AsyncIterator[bytes]:
        running = self._running.get(model_id)
        if not running:
            raise RuntimeError("Model is not active")

        url = f"{running.base_url}/runtime/models/{model_id}/chat/completions"
        timeout = request_timeout if request_timeout is not None else self.settings.llama_request_timeout_seconds
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
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
