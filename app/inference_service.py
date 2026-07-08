import asyncio
import codecs
import json
import logging
import os
import re
import shlex
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Optional

import httpx
import psutil
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from app.core.config import get_settings
from app.core.llama_failure import classify_llama_log, read_log_tail
from app.core.pool_lifecycle import FailureKind
from app.utils.schemas import sanitize_inference_messages
from app.core.device_manager import (
    AMD_VENDOR_ID,
    INTEL_VENDOR_ID,
    NVIDIA_VENDOR_ID,
    DeviceManager,
    get_supported_vendors,
    is_supported_vendor,
    parse_vulkaninfo_bdf_by_index,
    vulkaninfo_index_by_bdf,
    _parse_vulkan_vendor_id,
    _parse_vulkaninfo_gpu_memory_metrics,
)
from app.core.amdgpu_memory import (
    apply_amdgpu_live_metrics,
    is_vulkan_integrated_gpu,
    list_amdgpu_cards_by_bdf,
    list_amdgpu_device_paths,
    parse_vulkan_device_type,
    resolve_amdgpu_device_path,
)
from app.core.pci_bdf import normalize_pci_bdf
from app.core.intel_drm_memory import read_intel_vram_metrics
from app.core.nvidia_memory import (
    map_vulkan_index_to_nvidia_index,
    nvidia_smi_bdf_by_index,
    read_nvidia_gpu_usage,
    read_nvidia_memory_metrics,
)

logger = logging.getLogger(__name__)


def _log_gpu_passthrough_warning() -> None:
    try:
        result = subprocess.run(
            ["vulkaninfo", "--summary"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
        output = result.stdout.strip()
        stderr = result.stderr.strip()
    except Exception:
        return
    if stderr:
        logger.warning("vulkaninfo stderr: %s", stderr)
    if not output:
        return

    physical_gpus = 0
    has_software_renderer = False
    blocks = re.split(r"GPU(\d+):", output)
    i = 1
    while i + 1 < len(blocks):
        block = blocks[i + 1]
        i += 2
        type_match = re.search(r"deviceType\s*=\s*(.+)", block)
        device_type_str = type_match.group(1).strip().lower() if type_match else ""
        if "cpu" in device_type_str or "virtual_gpu" in device_type_str:
            has_software_renderer = True
            continue
        if re.search(r"deviceName\s*=\s*(.+)", block):
            physical_gpus += 1

    if physical_gpus == 0 and has_software_renderer:
        caps = os.environ.get("NVIDIA_DRIVER_CAPABILITIES", "")
        nvidia_icd = any(
            Path(path).is_file()
            for path in (
                "/usr/share/vulkan/icd.d/nvidia_icd.json",
                "/etc/vulkan/icd.d/nvidia_icd.json",
            )
        )
        logger.warning(
            "No physical Vulkan GPU detected in inference container. "
            "On mixed-vendor hosts, recreate inference after driver changes: "
            "./lmpanel up --build --force-recreate inference. "
            "NVIDIA_DRIVER_CAPABILITIES must include graphics (current: %r). "
            "nvidia_icd.json present: %s. "
            "Run bash scripts/verify-gpu-passthrough.sh for diagnostics.",
            caps or "unset",
            nvidia_icd,
        )


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

_GPU_OFFLOAD_VENDORS = frozenset({"vulkan"})
_VULKAN_RADV_PERFTEST = "nogttspill"


def _format_gpu_layers_for_cli(gpu_layers: int) -> str:
    if gpu_layers <= -1:
        return "all"
    return str(max(0, gpu_layers))


def _llama_offload_extra_args(vendor: str, gpu_layers: int, *, fit_to_vram: bool) -> list[str]:
    effective_vendor = vendor.removesuffix("_pool")
    if effective_vendor not in _GPU_OFFLOAD_VENDORS or gpu_layers == 0:
        return []

    args: list[str] = []
    if not fit_to_vram:
        args.extend(["--fit", "off"])
    args.extend(["--main-gpu", "0"])
    return args


def _validate_gpu_offload_from_log(log_path: str, vendor: str, gpu_layers: int) -> None:
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
            "llama-server has no usable GPU backend. Confirm the GPU is visible inside the inference "
            "container (vulkaninfo) and that host drivers are installed."
        )

    match = re.search(r"offloaded\s+(\d+)/(\d+)\s+layers", text, re.IGNORECASE)
    if match and int(match.group(1)) == 0 and int(match.group(2)) > 0:
        raise RuntimeError(
            "Model loaded with 0 GPU layers (CPU-only). Lower context length, keep GPU layers at 99 (all layers, or -1 for legacy), "
            "set LLAMA_FIT_TO_VRAM=false, and confirm the GPU is visible inside the inference container."
        )


def _coalesce_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class ActivateModelRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_id: int
    alias: str
    file_path: str
    mmproj_path: str | None = None
    context_length: int
    threads: int
    gpu_layers: int
    flash_attention_enabled: bool = False
    cache_type_k: str | None = None
    cache_type_v: str | None = None
    batch_size: int | None = None
    ubatch_size: int | None = None
    memory_mapping_enabled: bool = True
    vendor: str
    hardware_id: str
    hardware_ids: list[str] = []
    vram_ratios: list[int] = []
    split_mode: str = "layer"
    stable_hardware_id: str | None = None
    stable_hardware_ids: list[str] = []
    discourage_thinking: bool = False


@dataclass
class RunningModel:
    model_id: int
    alias: str
    hardware_id: str
    vendor: str
    port: int
    process: subprocess.Popen
    stable_hardware_ids: list[str] = field(default_factory=list, compare=False)
    command: list[str] = field(default_factory=list, compare=False)
    log_path: str = field(default="", compare=False)
    log_file: Optional[IO[bytes]] = field(default=None, compare=False)


class InferenceRuntime:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._running: dict[int, RunningModel] = {}
        self._tokens_processed = 0
        self._tokens_lock = threading.Lock()
        self._activation_lock = threading.Lock()
        self._model_failures: dict[int, FailureKind] = {}

    def get_failure_kind(self, model_id: int) -> FailureKind | None:
        return self._model_failures.get(model_id)

    def clear_failure_kind(self, model_id: int) -> None:
        self._model_failures.pop(model_id, None)

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

    def _resolve_flash_attn_flag(self, payload: ActivateModelRequest) -> str:
        """Return llama-server --flash-attn value (on/off/auto)."""
        model_wants = payload.flash_attention_enabled
        default = self.settings.vulkan_flash_attention_default.strip().lower()
        effective_vendor = payload.vendor.removesuffix("_pool")
        is_tensor_pool = payload.vendor.endswith("_pool") and payload.split_mode == "tensor"

        if is_tensor_pool and default != "off":
            if not model_wants:
                logger.info(
                    "Tensor split mode requires flash attention; forcing --flash-attn on for model %d (%s)",
                    payload.model_id,
                    payload.alias,
                )
            return "on"

        if effective_vendor != "vulkan":
            return "on" if model_wants else "off"

        if default == "on":
            if not model_wants:
                logger.info(
                    "Enabling flash attention for Vulkan inference on model %d (%s)",
                    payload.model_id,
                    payload.alias,
                )
            return "on"
        if default == "off":
            return "off"
        return "on" if model_wants else "auto"

    async def activate_model(self, payload: ActivateModelRequest) -> None:
        effective_vendor = payload.vendor.removesuffix("_pool")
        if not is_supported_vendor(effective_vendor):
            raise RuntimeError(f"Unsupported device vendor for this inference service: {payload.vendor}")

        with self._activation_lock:
            if payload.model_id in self._running:
                return

            self._ensure_stable_hardware_available(payload)

            # CPU-only devices must not offload layers to GPU
            gpu_layers = 0 if effective_vendor == "cpu" else payload.gpu_layers

            port = self.settings.llama_base_port + payload.model_id
            pool_launch = payload.vendor.endswith("_pool") and len(payload.hardware_ids) > 1
            env = self._build_env(
                payload.vendor,
                payload.hardware_id,
                payload.threads,
                payload.hardware_ids,
                stable_hardware_id=payload.stable_hardware_id,
                stable_hardware_ids=payload.stable_hardware_ids,
                pool_launch=pool_launch,
            )
            command = self._build_llama_command(payload, port, gpu_layers)

            logs_dir = Path(self.settings.logs_dir)
            logs_dir.mkdir(parents=True, exist_ok=True)
            log_path = logs_dir / f"llama-{payload.model_id}.log"

            try:
                log_file: IO[bytes] = open(log_path, "wb")
                logger.info(
                    "Launching llama-server for model %d (%s) on %s %s; log=%s; command=%s",
                    payload.model_id,
                    payload.alias,
                    payload.vendor,
                    payload.hardware_id,
                    log_path,
                    shlex.join(command),
                )
                process = subprocess.Popen(command, env=env, stdout=log_file, stderr=log_file)
            except FileNotFoundError as exc:
                raise RuntimeError(f"llama-server executable not found at {self.settings.llama_server_path}") from exc

            self._running[payload.model_id] = RunningModel(
                model_id=payload.model_id,
                alias=payload.alias,
                hardware_id=payload.hardware_id,
                vendor=payload.vendor,
                port=port,
                process=process,
                stable_hardware_ids=self._stable_hardware_ids_from_payload(payload),
                command=command,
                log_path=str(log_path),
                log_file=log_file,
            )
            if not await self.wait_until_healthy(payload.model_id):
                self._record_failure_from_log(payload.model_id, str(log_path))
                self.deactivate_model(payload.model_id)
                raise RuntimeError(f"Model {payload.alias} failed health check")

            try:
                _validate_gpu_offload_from_log(str(log_path), payload.vendor, gpu_layers)
            except RuntimeError:
                self._record_failure_from_log(payload.model_id, str(log_path))
                self.deactivate_model(payload.model_id)
                raise

            self.clear_failure_kind(payload.model_id)

    def deactivate_model(self, model_id: int) -> None:
        with self._activation_lock:
            running = self._running.pop(model_id, None)
            if not running:
                return
            self._terminate_running(running)

    def _terminate_running(self, running: "RunningModel") -> None:
        running.process.terminate()
        try:
            running.process.wait(timeout=10)
        except Exception:
            running.process.kill()
        if running.log_file is not None:
            try:
                running.log_file.close()
            except Exception:
                pass

    def _record_failure_from_log(self, model_id: int, log_path: str) -> FailureKind:
        kind = classify_llama_log(read_log_tail(log_path))
        self._model_failures[model_id] = kind
        if kind == FailureKind.DEVICE_LOST:
            logger.error("Model %d classified as device_lost from llama-server log", model_id)
        return kind

    def _mark_model_failed(self, model_id: int) -> FailureKind | None:
        """Drop a model whose llama-server connection failed.

        A connection error (refused/reset/no response) means the llama-server
        process is wedged or dead even though it may still be running and
        passing /health (e.g. a stuck worker thread). Killing it and clearing
        the entry makes the next watchdog tick's /alive check report
        tracked=False, which triggers automatic re-activation instead of every
        subsequent request hitting the same broken process.
        """
        with self._activation_lock:
            running = self._running.pop(model_id, None)
            if not running:
                return self._model_failures.get(model_id)
            failure_kind = self._record_failure_from_log(model_id, running.log_path)
            logger.error(
                "Model %d (%s) connection failed (%s); killing llama-server and clearing for auto-recovery",
                model_id,
                running.alias,
                failure_kind,
            )
            self._terminate_running(running)
            return failure_kind

    async def wait_until_healthy(self, model_id: int) -> bool:
        running = self._running.get(model_id)
        if not running:
            return False

        url = f"http://{self.settings.llama_host}:{running.port}/health"
        timeout = self.settings.llama_health_timeout_seconds
        startup_timeout = (
            max(self.settings.llama_startup_timeout_seconds, self.settings.pool_startup_timeout_seconds)
            if running.vendor.endswith("_pool")
            else self.settings.llama_startup_timeout_seconds
        )
        deadline = time.monotonic() + max(timeout, startup_timeout)

        while time.monotonic() < deadline:
            exit_code = running.process.poll()
            if exit_code is not None:
                logger.error(
                    "llama-server for model %d (%s) on %s %s exited early with code %d; log=%s; command=%s",
                    model_id,
                    running.alias,
                    running.vendor,
                    running.hardware_id,
                    exit_code,
                    running.log_path,
                    shlex.join(running.command),
                )
                return False
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(url)
                if response.status_code == 200:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)

        logger.error(
            "llama-server for model %d (%s) on %s %s did not become healthy within %d seconds; log=%s; command=%s",
            model_id,
            running.alias,
            running.vendor,
            running.hardware_id,
            max(timeout, self.settings.llama_startup_timeout_seconds),
            running.log_path,
            shlex.join(running.command),
        )
        return False

    async def chat_completion(self, model_id: int, payload: dict, *, request_timeout: int | None = None) -> dict:
        running = self._running.get(model_id)
        if not running:
            raise RuntimeError("Model is not active")
        request_payload = dict(payload)
        if "messages" in request_payload:
            request_payload["messages"] = sanitize_inference_messages(request_payload.get("messages") or [])
        url = f"http://{self.settings.llama_host}:{running.port}/v1/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=self._llama_http_timeout(for_stream=False)) as client:
                response = await client.post(url, json=request_payload)
        except httpx.HTTPError as exc:
            self._mark_model_failed(model_id)
            raise RuntimeError(f"Inference request error: {exc}") from exc
        response.raise_for_status()
        response_payload = response.json()
        self._record_usage_from_payload(response_payload)
        return response_payload

    async def stream_chat_completion(self, model_id: int, payload: dict, *, request_timeout: int | None = None):
        running = self._running.get(model_id)
        if not running:
            raise RuntimeError("Model is not active")

        request_payload = dict(payload)
        if "messages" in request_payload:
            request_payload["messages"] = sanitize_inference_messages(request_payload.get("messages") or [])

        url = f"http://{self.settings.llama_host}:{running.port}/v1/chat/completions"
        decoder = codecs.getincrementaldecoder("utf-8")("ignore")
        event_buffer = ""
        async with httpx.AsyncClient(timeout=self._llama_http_timeout(for_stream=True)) as client:
            try:
                async with client.stream("POST", url, json=request_payload) as response:
                    if response.is_error:
                        await response.aread()
                        raise RuntimeError(_runtime_error_detail(response))

                    async for chunk in response.aiter_bytes():
                        if chunk:
                            event_buffer = self._track_stream_chunk(event_buffer, decoder, chunk)
                            yield chunk
                    self._finalize_tracked_stream(event_buffer, decoder)
            except httpx.HTTPError as exc:
                self._mark_model_failed(model_id)
                raise RuntimeError(f"Inference stream error: {exc}") from exc

    def _resolve_llama_server_path(self) -> str:
        configured_path = Path(self.settings.llama_server_path)
        candidates = [configured_path]
        if os.name == "nt" and configured_path.suffix.lower() != ".exe":
            candidates.insert(0, configured_path.with_suffix(".exe"))

        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

        return str(configured_path)

    def _build_env(
        self,
        vendor: str,
        hardware_id: str,
        threads: int,
        hardware_ids: list[str] | None = None,
        stable_hardware_id: str | None = None,
        stable_hardware_ids: list[str] | None = None,
        *,
        pool_launch: bool = False,
    ) -> dict[str, str]:
        env = os.environ.copy()
        if vendor == "vulkan_pool":
            ids = hardware_ids if hardware_ids else [hardware_id]
            stable = stable_hardware_ids if stable_hardware_ids else ([stable_hardware_id] if stable_hardware_id else [])
            indices = self._resolve_vulkan_indices(ids, stable, pool_launch=pool_launch)
            env["GGML_VK_VISIBLE_DEVICES"] = ",".join(indices)
        elif vendor == "vulkan":
            stable = stable_hardware_ids if stable_hardware_ids else ([stable_hardware_id] if stable_hardware_id else [])
            indices = self._resolve_vulkan_indices([hardware_id], stable, pool_launch=False)
            env["GGML_VK_VISIBLE_DEVICES"] = ",".join(indices)
        elif vendor == "cpu":
            env["OMP_NUM_THREADS"] = str(max(1, threads))
        else:
            raise RuntimeError(f"Unknown device vendor: {vendor}")

        if vendor.removesuffix("_pool") == "vulkan":
            env.setdefault("RADV_PERFTEST", _VULKAN_RADV_PERFTEST)
        return env

    def _resolve_vulkan_indices(
        self,
        hardware_ids: list[str],
        stable_hardware_ids: list[str],
        *,
        pool_launch: bool = False,
    ) -> list[str]:
        """Translate each GPU's stable PCI BDF into its *current* live Vulkan index.

        The stored ``vulkan:{idx}`` enumeration index is not stable across reboots
        or driver updates, so launching with it can place a model on the wrong GPU.
        We re-resolve the index from the device's PCI BDF against a fresh
        ``vulkaninfo`` enumeration at launch time, falling back to the embedded
        index only when no BDF is available for single-GPU launches.
        """
        bdf_to_idx: dict[str, int] = {}
        output = self._run_command(["vulkaninfo"])
        if output:
            bdf_to_idx = vulkaninfo_index_by_bdf(output)

        if pool_launch and len(hardware_ids) > 1:
            if not bdf_to_idx:
                raise RuntimeError("vulkaninfo unavailable; cannot resolve pool GPU indices")
            if len(stable_hardware_ids) < len(hardware_ids):
                raise RuntimeError("Pool launch requires stable PCI BDF for every pool member")
            for position in range(len(hardware_ids)):
                stable = stable_hardware_ids[position].strip() if position < len(stable_hardware_ids) else ""
                if not stable:
                    raise RuntimeError(
                        f"Pool member {hardware_ids[position]} is missing a stable PCI BDF; "
                        "refusing positional Vulkan index fallback"
                    )

        indices: list[str] = []
        remap_log: dict[str, str] = {}
        for position, hardware_id in enumerate(hardware_ids):
            stable = stable_hardware_ids[position] if position < len(stable_hardware_ids) else None
            live_idx: int | None = None
            if stable:
                normalized = normalize_pci_bdf(stable)
                if normalized is not None:
                    live_idx = bdf_to_idx.get(normalized)
                    if pool_launch and len(hardware_ids) > 1 and live_idx is None:
                        raise RuntimeError(
                            f"Stable PCI BDF {normalized} for pool member {hardware_id} "
                            "is not present in the current Vulkan enumeration"
                        )
            if live_idx is not None:
                indices.append(str(live_idx))
                remap_log[hardware_id] = f"{stable}->{live_idx}"
            else:
                if pool_launch and len(hardware_ids) > 1:
                    raise RuntimeError(
                        f"Could not resolve live Vulkan index for pool member {hardware_id}"
                    )
                fallback = hardware_id.split(":")[-1]
                indices.append(fallback)
                remap_log[hardware_id] = f"fallback->{fallback}"

        if pool_launch and len(indices) > 1 and len(set(indices)) != len(indices):
            raise RuntimeError(f"Duplicate Vulkan indices after BDF remap: {indices}")

        logger.info(
            "Vulkan index remap for %s launch: %s",
            "pool" if pool_launch else "single",
            remap_log,
        )
        return indices

    def _build_llama_command(self, payload: ActivateModelRequest, port: int, gpu_layers: int) -> list[str]:
        flash_attn_flag = self._resolve_flash_attn_flag(payload)

        batch_size = payload.batch_size
        ubatch_size = payload.ubatch_size
        if payload.vendor.endswith("_pool"):
            if not batch_size:
                batch_size = self.settings.pool_default_batch_size
            if not ubatch_size:
                ubatch_size = self.settings.pool_default_ubatch_size

        command = [
            self._resolve_llama_server_path(),
            "-m",
            payload.file_path,
            "--host",
            self.settings.llama_host,
            "--port",
            str(port),
            "-c",
            str(payload.context_length),
            "--threads",
            str(payload.threads),
            "--threads-batch",
            str(payload.threads),
            "--n-gpu-layers",
            _format_gpu_layers_for_cli(gpu_layers),
            "--flash-attn",
            flash_attn_flag,
        ]
        if payload.cache_type_k:
            command.extend(["--cache-type-k", payload.cache_type_k])
        if payload.cache_type_v:
            command.extend(["--cache-type-v", payload.cache_type_v])
        if batch_size:
            command.extend(["--batch-size", str(batch_size)])
        if ubatch_size:
            command.extend(["--ubatch-size", str(ubatch_size)])
        command.extend(
            _llama_offload_extra_args(
                payload.vendor,
                gpu_layers,
                fit_to_vram=self.settings.llama_fit_to_vram,
            )
        )
        if not payload.memory_mapping_enabled:
            command.append("--no-mmap")
        if payload.mmproj_path:
            command.extend(["--mmproj", payload.mmproj_path])
        command.extend(
            self._build_vendor_args(
                payload.vendor,
                payload.vram_ratios,
                payload.split_mode,
            )
        )
        command.append("--jinja")
        if payload.discourage_thinking:
            command.extend(["--reasoning", "off", "--reasoning-budget", "0"])
        return command

    def _build_vendor_args(
        self,
        vendor: str,
        vram_ratios: list[int] | None = None,
        split_mode: str = "layer",
    ) -> list[str]:
        if vendor.endswith("_pool"):
            args: list[str] = []
            if vram_ratios and len(vram_ratios) >= 2:
                args.extend(["--tensor-split", ",".join(str(r) for r in vram_ratios)])
            args.extend(["--split-mode", split_mode])
            return args

        return []

    @staticmethod
    def _stable_hardware_ids_from_payload(payload: ActivateModelRequest) -> list[str]:
        ids = [value.strip() for value in payload.stable_hardware_ids if value and value.strip()]
        if not ids and payload.stable_hardware_id and payload.stable_hardware_id.strip():
            ids = [payload.stable_hardware_id.strip()]
        return ids

    def _ensure_stable_hardware_available(self, payload: ActivateModelRequest) -> None:
        requested = self._stable_hardware_ids_from_payload(payload)
        if not requested:
            return

        requested_set = set(requested)
        for running in self._running.values():
            if running.process.poll() is not None:
                continue
            overlap = requested_set.intersection(running.stable_hardware_ids)
            if overlap:
                raise RuntimeError(
                    f"GPU already in use by model {running.alias} (stable id: {', '.join(sorted(overlap))})"
                )

    def status_payload(self) -> dict:
        supported_vendors = get_supported_vendors()
        detected_devices = [device for device in device_manager.detect_local() if device.vendor in supported_vendors]
        dynamic_metrics = self._collect_dynamic_metrics()
        models_by_hardware_id: dict[str, list[dict]] = {}

        for running in self._running.values():
            if running.process.poll() is not None:
                continue

            hardware_metrics = dynamic_metrics.get(running.hardware_id, {})
            process_memory_by_pid = hardware_metrics.get("process_memory_by_pid", {})
            process_memory_mb = process_memory_by_pid.get(running.process.pid)
            if process_memory_mb is None:
                process_memory_mb = self._process_memory_mb(running.process.pid)

            models_by_hardware_id.setdefault(running.hardware_id, []).append(
                {
                    "model_id": running.model_id,
                    "alias": running.alias,
                    "pid": running.process.pid,
                    "memory_used_mb": process_memory_mb,
                }
            )

        devices: list[dict] = []
        for device in detected_devices:
            device_models = sorted(models_by_hardware_id.get(device.hardware_id, []), key=lambda row: row["model_id"])
            hardware_metrics = dynamic_metrics.get(device.hardware_id, {})
            process_memory_total = sum(model["memory_used_mb"] for model in device_models)
            memory_used_mb = int(hardware_metrics.get("memory_used_mb") or 0)
            process_memory_by_pid = hardware_metrics.get("process_memory_by_pid", {})
            if device_models and memory_used_mb > 0 and not process_memory_by_pid and process_memory_total < memory_used_mb:
                self._distribute_shared_memory(device_models, memory_used_mb)
                process_memory_total = sum(model["memory_used_mb"] for model in device_models)
            if memory_used_mb <= 0 and process_memory_total > 0:
                memory_used_mb = process_memory_total

            usage_percent = hardware_metrics.get("usage_percent")
            usage_source = hardware_metrics.get("usage_source") if usage_percent is not None else "unavailable"

            gpu_usage_percent = hardware_metrics.get("usage_percent") if device.device_type.lower() != "cpu" else None
            gpu_usage_source = hardware_metrics.get("usage_source") if gpu_usage_percent is not None else "unavailable"

            devices.append(
                {
                    "hardware_id": device.hardware_id,
                    "stable_hardware_id": device.stable_hardware_id,
                    "stable_hardware_id_source": device.stable_hardware_id_source,
                    "name": device.name,
                    "vendor": device.vendor,
                    "device_type": device.device_type,
                    "memory_total_mb": hardware_metrics.get("memory_total_mb") or device.memory_mb,
                    "memory_used_mb": memory_used_mb,
                    "gpu_usage_percent": gpu_usage_percent,
                    "gpu_usage_source": gpu_usage_source,
                    "usage_percent": usage_percent,
                    "usage_source": usage_source,
                    "memory_source": hardware_metrics.get("memory_source", "processes"),
                    "gtt_total_mb": hardware_metrics.get("gtt_total_mb"),
                    "gtt_used_mb": hardware_metrics.get("gtt_used_mb"),
                    "gtt_source": hardware_metrics.get("gtt_source"),
                    "models": device_models,
                }
            )

        return {
            "status": "ok",
            "devices": devices,
            "tokens_processed": self.tokens_processed,
        }

    @property
    def tokens_processed(self) -> int:
        with self._tokens_lock:
            return self._tokens_processed

    def _record_usage_from_payload(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return

        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return

        total_tokens = _coalesce_int(usage.get("total_tokens"))
        if total_tokens is None:
            total_tokens = _coalesce_int(usage.get("totalTokens"))
        if total_tokens is None or total_tokens <= 0:
            return

        with self._tokens_lock:
            self._tokens_processed += total_tokens

    def _track_stream_chunk(self, event_buffer: str, decoder, chunk: bytes) -> str:
        try:
            event_buffer += decoder.decode(chunk)
            return self._consume_sse_events(event_buffer)
        except Exception:
            logger.exception("Failed to inspect streamed completion chunk for usage stats")
            return event_buffer

    def _finalize_tracked_stream(self, event_buffer: str, decoder) -> None:
        try:
            event_buffer += decoder.decode(b"", final=True)
            self._consume_sse_events(event_buffer, final=True)
        except Exception:
            logger.exception("Failed to finalize streamed completion usage stats")

    def _consume_sse_events(self, buffer: str, final: bool = False) -> str:
        normalized_buffer = buffer.replace("\r\n", "\n")
        events = normalized_buffer.split("\n\n")

        if not final:
            remainder = events.pop() if events else ""
        else:
            remainder = ""

        for event in events:
            self._record_usage_from_sse_event(event)

        if final and remainder:
            self._record_usage_from_sse_event(remainder)

        return remainder

    def _record_usage_from_sse_event(self, event: str) -> None:
        data_lines: list[str] = []
        for raw_line in event.split("\n"):
            if raw_line.startswith("data:"):
                data_lines.append(raw_line[5:].lstrip())

        if not data_lines:
            return

        data = "\n".join(data_lines).strip()
        if not data or data == "[DONE]":
            return

        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return

        self._record_usage_from_payload(payload)

    def _collect_dynamic_metrics(self) -> dict[str, dict]:
        metrics: dict[str, dict] = {}

        cpu_memory = psutil.virtual_memory()
        metrics["cpu:0"] = {
            "usage_percent": round(psutil.cpu_percent(), 1),
            "usage_source": "system",
            "memory_used_mb": int(cpu_memory.used / (1024 * 1024)),
            "memory_total_mb": int(cpu_memory.total / (1024 * 1024)),
            "memory_source": "system",
            "process_memory_by_pid": {},
        }

        metrics.update(self._collect_vulkan_metrics())
        return metrics

    def _collect_vulkan_metrics(self) -> dict[str, dict]:
        output = self._run_command(["vulkaninfo"])
        metrics: dict[str, dict] = {}
        amd_vulkan_indices: list[int] = []
        amd_vulkan_by_idx: dict[int, str] = {}
        amd_integrated_by_idx: dict[int, bool] = {}
        intel_vulkan_by_idx: dict[int, str] = {}
        nvidia_vulkan_by_idx: dict[int, str] = {}
        memory_by_idx = _parse_vulkaninfo_gpu_memory_metrics(output) if output else {}
        bdf_by_idx = parse_vulkaninfo_bdf_by_index(output) if output else {}
        if output:
            blocks = re.split(r"GPU(\d+):", output)
            i = 1
            while i + 1 < len(blocks):
                try:
                    idx = int(blocks[i])
                except ValueError:
                    i += 2
                    continue
                block = blocks[i + 1]
                i += 2

                vendor_id = _parse_vulkan_vendor_id(block)
                pci_bdf = bdf_by_idx.get(idx)
                if vendor_id == AMD_VENDOR_ID:
                    amd_vulkan_indices.append(idx)
                    if pci_bdf:
                        amd_vulkan_by_idx[idx] = pci_bdf
                    amd_integrated_by_idx[idx] = is_vulkan_integrated_gpu(parse_vulkan_device_type(block))

                if vendor_id == INTEL_VENDOR_ID:
                    if pci_bdf:
                        intel_vulkan_by_idx[idx] = pci_bdf

                if vendor_id == NVIDIA_VENDOR_ID:
                    if pci_bdf:
                        nvidia_vulkan_by_idx[idx] = pci_bdf

                heap_metrics = memory_by_idx.get(idx)
                if not heap_metrics or heap_metrics["total_mb"] <= 0:
                    continue

                hardware_id = f"vulkan:{idx}"
                metrics[hardware_id] = {
                    "usage_percent": None,
                    "usage_source": "unavailable",
                    "memory_used_mb": heap_metrics["used_mb"],
                    "memory_total_mb": heap_metrics["total_mb"],
                    "memory_source": "vulkaninfo",
                    "process_memory_by_pid": {},
                }

        # Prefer amdgpu sysfs counters when available. For integrated/APU GPUs include GTT.
        try:
            amd_cards_by_bdf = list_amdgpu_cards_by_bdf()
            amd_ordered_paths = list_amdgpu_device_paths()
            # Positional fallback is only safe with a single AMD GPU; with multiple
            # GPUs and no PCI BDF, enumeration order need not match sysfs cardN order.
            allow_positional = len(amd_vulkan_indices) <= 1
            for position, vulkan_idx in enumerate(amd_vulkan_indices):
                pci_bdf = amd_vulkan_by_idx.get(vulkan_idx)
                device_path = resolve_amdgpu_device_path(
                    pci_bdf,
                    position=position if allow_positional else None,
                    cards_by_bdf=amd_cards_by_bdf,
                    ordered_paths=amd_ordered_paths,
                )
                if device_path is None:
                    continue
                hardware_id = f"vulkan:{vulkan_idx}"
                metric = metrics.setdefault(
                    hardware_id,
                    {
                        "usage_percent": None,
                        "usage_source": "unavailable",
                        "memory_used_mb": 0,
                        "memory_total_mb": 0,
                        "memory_source": "processes",
                        "process_memory_by_pid": {},
                    },
                )

                integrated = amd_integrated_by_idx.get(vulkan_idx, False)
                apply_amdgpu_live_metrics(
                    metric,
                    device_path,
                    pci_bdf=pci_bdf,
                    integrated=integrated,
                )
        except Exception:
            pass

        for vulkan_idx, pci_bdf in intel_vulkan_by_idx.items():
            hardware_id = f"vulkan:{vulkan_idx}"
            metric = metrics.get(hardware_id)
            if metric is None:
                continue
            try:
                intel_metrics = read_intel_vram_metrics(pci_bdf)
            except Exception:
                continue
            if not intel_metrics:
                continue
            if intel_metrics.get("memory_total_mb"):
                metric["memory_total_mb"] = intel_metrics["memory_total_mb"]
            if intel_metrics.get("memory_used_mb") is not None:
                metric["memory_used_mb"] = intel_metrics["memory_used_mb"]
            if intel_metrics.get("memory_source"):
                metric["memory_source"] = intel_metrics["memory_source"]
            process_memory = intel_metrics.get("process_memory_by_pid")
            if isinstance(process_memory, dict) and process_memory:
                metric["process_memory_by_pid"] = process_memory

        # Prefer nvidia-smi counters for NVIDIA GPUs (vulkaninfo usage is inaccurate).
        try:
            nvidia_bdf_map = nvidia_smi_bdf_by_index()
            for vulkan_idx, pci_bdf in nvidia_vulkan_by_idx.items():
                hardware_id = f"vulkan:{vulkan_idx}"
                metric = metrics.get(hardware_id)
                if metric is None:
                    continue
                nvidia_idx = map_vulkan_index_to_nvidia_index(pci_bdf, nvidia_bdf_map)
                if nvidia_idx is None:
                    continue
                nvidia_metrics = read_nvidia_memory_metrics(nvidia_idx)
                if nvidia_metrics.get("memory_total_mb"):
                    metric["memory_total_mb"] = nvidia_metrics["memory_total_mb"]
                if nvidia_metrics.get("memory_used_mb") is not None:
                    metric["memory_used_mb"] = nvidia_metrics["memory_used_mb"]
                if nvidia_metrics.get("memory_source"):
                    metric["memory_source"] = nvidia_metrics["memory_source"]
                gpu_usage = read_nvidia_gpu_usage(nvidia_idx)
                if gpu_usage is not None:
                    metric["usage_percent"] = gpu_usage
                    metric["usage_source"] = "nvidia-smi"
        except Exception:
            pass

        return metrics

    @staticmethod
    def _flatten_metric_entries(value: object, prefix: tuple[str, ...] = ()) -> list[tuple[str, str]]:
        entries: list[tuple[str, str]] = []
        if isinstance(value, dict):
            for key, child in value.items():
                entries.extend(InferenceRuntime._flatten_metric_entries(child, (*prefix, str(key).lower())))
            return entries

        if isinstance(value, list):
            for index, child in enumerate(value):
                entries.extend(InferenceRuntime._flatten_metric_entries(child, (*prefix, str(index))))
            return entries

        entries.append((" ".join(prefix), str(value).strip()))
        return entries

    @staticmethod
    def _parse_percentage(value: str) -> float | None:
        match = re.search(r"(-?\d+(?:\.\d+)?)\s*%?", value)
        if not match:
            return None
        try:
            return round(float(match.group(1)), 1)
        except ValueError:
            return None

    @staticmethod
    def _parse_size_to_bytes(value: str) -> int | None:
        match = re.search(r"(-?\d+(?:\.\d+)?)\s*(bytes|byte|b|kbytes|kb|kib|mbytes|mb|mib|gbytes|gb|gib|tbytes|tb|tib)?", value, re.IGNORECASE)
        if not match:
            return None

        try:
            amount = float(match.group(1))
        except ValueError:
            return None

        unit = (match.group(2) or "bytes").lower()
        multipliers = {
            "bytes": 1,
            "byte": 1,
            "b": 1,
            "kbytes": 1024,
            "kb": 1024,
            "kib": 1024,
            "mbytes": 1024**2,
            "mb": 1024**2,
            "mib": 1024**2,
            "gbytes": 1024**3,
            "gb": 1024**3,
            "gib": 1024**3,
            "tbytes": 1024**4,
            "tb": 1024**4,
            "tib": 1024**4,
        }
        return int(amount * multipliers.get(unit, 1))

    @staticmethod
    def _distribute_shared_memory(models: list[dict], total_memory_mb: int) -> None:
        if not models or total_memory_mb <= 0:
            return

        weights = [max(0, int(model.get("memory_used_mb") or 0)) for model in models]
        if sum(weights) <= 0:
            weights = [1] * len(models)

        weight_total = sum(weights)
        allocations = [int(total_memory_mb * weight / weight_total) for weight in weights]
        remainder = total_memory_mb - sum(allocations)
        indices = sorted(range(len(weights)), key=lambda index: weights[index], reverse=True)
        for offset in range(remainder):
            allocations[indices[offset % len(indices)]] += 1

        for model, allocation in zip(models, allocations):
            model["memory_used_mb"] = allocation

    @staticmethod
    def _run_command(command: list[str]) -> str:
        try:
            output = subprocess.check_output(command, stderr=subprocess.DEVNULL, text=True)
        except Exception:
            return ""
        return output.strip()

    @staticmethod
    def _process_memory_mb(pid: int) -> int:
        try:
            process = psutil.Process(pid)
            return int(process.memory_info().rss / (1024 * 1024))
        except Exception:
            return 0

    @staticmethod
    def _parse_int(value: str) -> int | None:
        text = value.strip()
        if not text or text.upper() == "N/A":
            return None
        try:
            return int(float(text))
        except ValueError:
            return None

    @staticmethod
    def _parse_float(value: str) -> float | None:
        text = value.strip()
        if not text or text.upper() == "N/A":
            return None
        try:
            return round(float(text), 1)
        except ValueError:
            return None

    @staticmethod
    def _read_sysfs_int(path: Path) -> int | None:
        try:
            return int(path.read_text().strip())
        except Exception:
            return None

    @classmethod
    def _read_sysfs_percentage(cls, path: Path) -> float | None:
        value = cls._read_sysfs_int(path)
        if value is None:
            return None
        return round(float(value), 1)


def _log_toolchain_versions() -> None:
    build_commit_path = Path("/opt/llama.cpp/BUILD_COMMIT")
    if build_commit_path.is_file():
        commit = build_commit_path.read_text(encoding="utf-8").strip()
        if commit:
            logger.info("llama.cpp build commit: %s", commit)

    try:
        result = subprocess.run(
            ["vulkaninfo", "--summary"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
        driver_match = re.search(r"driverVersion\s*=\s*(\S+)", result.stdout)
        if driver_match:
            logger.info("Vulkan driver version: %s", driver_match.group(1))
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_: FastAPI):
    _log_toolchain_versions()
    _log_gpu_passthrough_warning()
    yield


app = FastAPI(title="LmPanel Inference Service", lifespan=lifespan)
runtime = InferenceRuntime()
device_manager = DeviceManager()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "active_models": sorted(runtime._running.keys())}


@app.get("/runtime/info")
def runtime_info() -> dict:
    return {
        "status": "ok",
        "supported_vendors": sorted(get_supported_vendors()),
        "active_models": sorted(runtime._running.keys()),
    }


@app.get("/runtime/devices")
def runtime_devices() -> dict:
    devices = [
        {
            "hardware_id": device.hardware_id,
            "stable_hardware_id": device.stable_hardware_id,
            "stable_hardware_id_source": device.stable_hardware_id_source,
            "name": device.name,
            "vendor": device.vendor,
            "device_type": device.device_type,
            "memory_mb": device.memory_mb,
            "max_threads": device.max_threads,
            "max_slots": device.max_slots,
            "pci_vendor_id": device.pci_vendor_id,
        }
        for device in device_manager.detect_local()
        if is_supported_vendor(device.vendor)
    ]
    return {"status": "ok", "devices": devices}


@app.get("/runtime/status")
def runtime_status() -> dict:
    return runtime.status_payload()


@app.post("/runtime/models/activate")
async def activate_model(payload: ActivateModelRequest) -> dict:
    try:
        await runtime.activate_model(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "model_id": payload.model_id}


@app.post("/runtime/models/{model_id}/deactivate")
def deactivate_model(model_id: int) -> dict:
    runtime.deactivate_model(model_id)
    return {"status": "ok"}


@app.get("/runtime/models/{model_id}/alive")
def model_alive(model_id: int) -> dict:
    """Report whether the model's llama-server process is still running.

    Used by the backend watchdog to detect crashed processes for auto-recovery.
    ``tracked`` distinguishes "not running because it crashed" from "never started
    on this runtime"."""
    running = runtime._running.get(model_id)
    alive = bool(running and running.process.poll() is None)
    pid = running.process.pid if running else None
    failure_kind = runtime.get_failure_kind(model_id)
    return {
        "status": "ok",
        "alive": alive,
        "tracked": running is not None,
        "pid": pid,
        "failure_kind": failure_kind.value if failure_kind else None,
    }


@app.get("/runtime/models/{model_id}/health")
async def model_health(model_id: int) -> dict:
    if await runtime.wait_until_healthy(model_id):
        return {"status": "ok"}
    raise HTTPException(status_code=503, detail="Model is not healthy")


@app.post("/runtime/models/{model_id}/chat/completions")
async def chat_completion(model_id: int, payload: dict):
    try:
        if payload.get("stream"):
            return StreamingResponse(
                runtime.stream_chat_completion(model_id, payload),
                media_type="text/event-stream",
            )
        return await runtime.chat_completion(model_id, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
