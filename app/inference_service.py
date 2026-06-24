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
from app.utils.schemas import sanitize_inference_messages
from app.core.device_manager import (
    AMD_VENDOR_ID,
    INTEL_VENDOR_ID,
    DeviceManager,
    get_supported_vendors,
    is_supported_vendor,
    _parse_vulkan_vendor_id,
    _parse_vulkaninfo_gpu_memory_metrics,
)
from app.core.amdgpu_memory import (
    is_vulkan_integrated_gpu,
    list_amdgpu_device_paths,
    parse_vulkan_device_type,
    read_amdgpu_memory_metrics,
)
from app.core.intel_drm_memory import parse_vulkan_pci_bdf, read_intel_vram_metrics

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
            "On NVIDIA hosts, run bash scripts/configure-gpu-compose.sh, then "
            "docker compose up -d --build --force-recreate inference. "
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
    if not vendor.endswith("_pool"):
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

    async def activate_model(self, payload: ActivateModelRequest) -> None:
        effective_vendor = payload.vendor.removesuffix("_pool")
        if not is_supported_vendor(effective_vendor):
            raise RuntimeError(f"Unsupported device vendor for this inference service: {payload.vendor}")
        if payload.model_id in self._running:
            return

        self._ensure_stable_hardware_available(payload)

        port = self.settings.llama_base_port + payload.model_id
        env = self._build_env(payload.vendor, payload.hardware_id, payload.threads, payload.hardware_ids)
        flash_attn_enabled = payload.flash_attention_enabled

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
            "--n-gpu-layers",
            _format_gpu_layers_for_cli(payload.gpu_layers),
            "--flash-attn",
            "on" if flash_attn_enabled else "off",
        ]
        command.extend(
            _llama_offload_extra_args(
                payload.vendor,
                payload.gpu_layers,
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
            self.deactivate_model(payload.model_id)
            raise RuntimeError(f"Model {payload.alias} failed health check")

        try:
            _validate_gpu_offload_from_log(str(log_path), payload.vendor, payload.gpu_layers)
        except RuntimeError:
            self.deactivate_model(payload.model_id)
            raise

    def deactivate_model(self, model_id: int) -> None:
        running = self._running.pop(model_id, None)
        if not running:
            return
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

    async def wait_until_healthy(self, model_id: int) -> bool:
        running = self._running.get(model_id)
        if not running:
            return False

        url = f"http://{self.settings.llama_host}:{running.port}/health"
        timeout = self.settings.llama_health_timeout_seconds
        deadline = time.monotonic() + max(timeout, self.settings.llama_startup_timeout_seconds)

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
        timeout = request_timeout if request_timeout is not None else self.settings.llama_request_timeout_seconds
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=request_payload)
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
        timeout = request_timeout if request_timeout is not None else self.settings.llama_request_timeout_seconds
        async with httpx.AsyncClient(timeout=timeout) as client:
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

    def _build_env(self, vendor: str, hardware_id: str, threads: int, hardware_ids: list[str] | None = None) -> dict[str, str]:
        env = os.environ.copy()
        if vendor == "vulkan_pool":
            ids = hardware_ids if hardware_ids else [hardware_id]
            indices = [hid.split(":")[-1] for hid in ids]
            env["GGML_VK_VISIBLE_DEVICES"] = ",".join(indices)
        elif vendor == "vulkan":
            env["GGML_VK_VISIBLE_DEVICES"] = hardware_id.split(":")[-1]
        elif vendor == "cpu":
            env["OMP_NUM_THREADS"] = str(max(1, threads))
        else:
            raise RuntimeError(f"Unknown device vendor: {vendor}")
        return env

    def _build_vendor_args(
        self,
        vendor: str,
        vram_ratios: list[int] | None = None,
        split_mode: str = "layer",
    ) -> list[str]:
        if vendor.endswith("_pool"):
            args: list[str] = []
            if split_mode == "tensor" and vram_ratios and len(vram_ratios) >= 2:
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
        amd_integrated_by_idx: dict[int, bool] = {}
        intel_vulkan_by_idx: dict[int, str] = {}
        memory_by_idx = _parse_vulkaninfo_gpu_memory_metrics(output) if output else {}
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
                if vendor_id == AMD_VENDOR_ID:
                    amd_vulkan_indices.append(idx)
                    amd_integrated_by_idx[idx] = is_vulkan_integrated_gpu(parse_vulkan_device_type(block))

                if vendor_id == INTEL_VENDOR_ID:
                    pci_bdf = parse_vulkan_pci_bdf(block)
                    if pci_bdf:
                        intel_vulkan_by_idx[idx] = pci_bdf

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
            amd_card_paths = list_amdgpu_device_paths()
            for vulkan_idx, device_path in zip(amd_vulkan_indices, amd_card_paths, strict=False):
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

                usage = self._read_sysfs_percentage(device_path / "gpu_busy_percent")
                if usage is not None:
                    metric["usage_percent"] = usage
                    metric["usage_source"] = "sysfs"

                integrated = amd_integrated_by_idx.get(vulkan_idx, False)
                amdgpu_metrics = read_amdgpu_memory_metrics(device_path, integrated=integrated)
                if amdgpu_metrics.get("memory_total_mb"):
                    metric["memory_total_mb"] = amdgpu_metrics["memory_total_mb"]
                if amdgpu_metrics.get("memory_used_mb") is not None:
                    metric["memory_used_mb"] = amdgpu_metrics["memory_used_mb"]
                if amdgpu_metrics.get("memory_source"):
                    metric["memory_source"] = amdgpu_metrics["memory_source"]
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


@asynccontextmanager
async def lifespan(_: FastAPI):
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
