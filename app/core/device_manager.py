import logging
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx
import psutil
from sqlalchemy.orm import Session

from app.core.amdgpu_memory import (
    is_vulkan_integrated_gpu,
    list_amdgpu_cards_by_bdf,
    list_amdgpu_device_paths,
    read_amdgpu_memory_metrics,
    resolve_amdgpu_device_path,
)
from app.core.config import get_settings
from app.core.gpu_pool_manager import delete_unavailable_devices
from app.core.pci_bdf import parse_vulkan_pci_bdf
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.inference_manager import InferenceManager
from app.models.device import Device

logger = logging.getLogger(__name__)

AMD_VENDOR_ID = 0x1002
INTEL_VENDOR_ID = 0x8086
NVIDIA_VENDOR_ID = 0x10de


def get_supported_vendors() -> set[str]:
    settings = get_settings()
    configured = settings.supported_device_list()
    if configured:
        return set(configured)

    return {"cpu", "vulkan"}


def is_supported_vendor(vendor: str) -> bool:
    return vendor in get_supported_vendors()


@dataclass
class DetectedDevice:
    hardware_id: str
    stable_hardware_id: str | None
    stable_hardware_id_source: str | None
    name: str
    vendor: str
    device_type: str
    memory_mb: int
    max_threads: int = 0
    max_slots: int = 0
    pci_vendor_id: int | None = None


class DeviceManager:
    def detect_all(self) -> list[DetectedDevice]:
        remote = self._detect_runtime_devices()
        if remote:
            return remote

        configured = self._detect_configured_devices()
        if configured:
            return configured

        return self.detect_local()

    def detect_local(self) -> list[DetectedDevice]:
        devices: list[DetectedDevice] = []
        devices.extend(self._detect_vulkan())
        devices.extend(self._detect_cpu())
        return devices

    def default_name_for_device(self, device: Device) -> str:
        cached = getattr(self, "_default_names_by_hardware_id", {}).get(device.hardware_id)
        if cached:
            return cached

        for detected in self.detect_all():
            if detected.hardware_id == device.hardware_id:
                return detected.name

        return device.name

    def sync_detected_devices(
        self,
        db: Session,
        *,
        auto_enable_defaults: bool = False,
        inference: "InferenceManager | None" = None,
    ) -> list[Device]:
        detected = self.detect_all()
        self._default_names_by_hardware_id = {item.hardware_id: item.name for item in detected}
        existing_rows = db.query(Device).all()
        existing_by_hardware_id = {device.hardware_id: device for device in existing_rows}
        existing_by_stable_id = {
            device.stable_hardware_id: device
            for device in existing_rows
            if device.stable_hardware_id
        }
        detected_hardware_ids = {device.hardware_id for device in detected}
        detected_stable_ids = {
            device.stable_hardware_id for device in detected if device.stable_hardware_id
        }
        gpu_detected = any(device.device_type == "gpu" and device.vendor != "cpu" for device in detected)
        kept_row_ids: set[int] = set()

        for detected_device in detected:
            row = existing_by_hardware_id.get(detected_device.hardware_id)
            if row is None and detected_device.stable_hardware_id:
                candidate = existing_by_stable_id.get(detected_device.stable_hardware_id)
                if candidate is not None and candidate.id not in kept_row_ids:
                    row = candidate

            enabled = self._should_auto_enable(detected_device, gpu_detected) if auto_enable_defaults else False
            if row is None:
                row = Device(
                    hardware_id=detected_device.hardware_id,
                    stable_hardware_id=detected_device.stable_hardware_id,
                    stable_hardware_id_source=detected_device.stable_hardware_id_source,
                    name=detected_device.name,
                    vendor=detected_device.vendor,
                    device_type=detected_device.device_type,
                    memory_mb=detected_device.memory_mb,
                    enabled=enabled,
                    max_threads=detected_device.max_threads,
                    max_slots=detected_device.max_slots,
                )
                db.add(row)
                db.flush()
            else:
                if row.hardware_id != detected_device.hardware_id:
                    existing_by_hardware_id.pop(row.hardware_id, None)
                    row.hardware_id = detected_device.hardware_id
                row.stable_hardware_id = detected_device.stable_hardware_id
                row.stable_hardware_id_source = detected_device.stable_hardware_id_source
                row.name = detected_device.name
                row.vendor = detected_device.vendor
                row.device_type = detected_device.device_type
                row.memory_mb = detected_device.memory_mb
                if row.device_type == "cpu":
                    row.max_threads = detected_device.max_threads or row.max_threads
                    row.max_slots = max(0, detected_device.max_slots)

            kept_row_ids.add(row.id)
            existing_by_hardware_id[row.hardware_id] = row
            if detected_device.stable_hardware_id:
                existing_by_stable_id[detected_device.stable_hardware_id] = row

        removed_device_ids = delete_unavailable_devices(
            db,
            detected_hardware_ids,
            inference,
            detected_stable_hardware_ids=detected_stable_ids,
            keep_device_ids=kept_row_ids,
        )
        if removed_device_ids:
            logger.info(
                "Removed %s device(s) no longer reported by active runtimes: %s",
                len(removed_device_ids),
                removed_device_ids,
            )

        db.commit()
        return db.query(Device).order_by(Device.priority.asc(), Device.id.asc()).all()

    @staticmethod
    def _should_auto_enable(device: DetectedDevice, gpu_detected: bool) -> bool:
        if gpu_detected:
            return device.device_type == "gpu" and device.vendor != "cpu"

        return device.device_type == "cpu" or device.vendor == "cpu"

    def _detect_runtime_devices(self) -> list[DetectedDevice]:
        settings = get_settings()
        if not settings.inference_runtime_urls.strip():
            return []

        devices_by_id: dict[str, DetectedDevice] = {}
        runtime_map = settings.inference_runtime_url_map()
        timeout = settings.inference_service_timeout_seconds

        for runtime_vendor, base_url in runtime_map.items():
            try:
                with httpx.Client(timeout=timeout) as client:
                    response = client.get(f"{base_url}/runtime/devices")
                    response.raise_for_status()
            except Exception as exc:
                logger.warning("Failed to fetch devices from runtime %s at %s: %s", runtime_vendor, base_url, exc)
                continue

            payload = response.json()
            rows = payload.get("devices", []) if isinstance(payload, dict) else []
            for row in rows:
                device = self._parse_runtime_device(row)
                if not device:
                    continue
                if runtime_vendor != "default" and device.vendor != runtime_vendor:
                    continue
                devices_by_id[device.hardware_id] = device

        return list(devices_by_id.values())

    @staticmethod
    def _parse_runtime_device(row: object) -> DetectedDevice | None:
        if not isinstance(row, dict):
            return None

        try:
            hardware_id = str(row["hardware_id"])
            stable_hardware_id = _normalize_optional_identifier(row.get("stable_hardware_id"))
            stable_hardware_id_source = _normalize_identifier_source(row.get("stable_hardware_id_source"))
            name = str(row["name"])
            vendor = str(row["vendor"])
            device_type = str(row.get("device_type", "gpu"))
            memory_mb = int(row.get("memory_mb", 0) or 0)
            max_threads = int(row.get("max_threads", 0) or 0)
            max_slots = int(row.get("max_slots", 0) or 0)
            pci_vendor_raw = row.get("pci_vendor_id")
            pci_vendor_id = int(pci_vendor_raw) if pci_vendor_raw is not None else None
        except (KeyError, TypeError, ValueError):
            return None

        return DetectedDevice(
            hardware_id=hardware_id,
            stable_hardware_id=stable_hardware_id,
            stable_hardware_id_source=stable_hardware_id_source,
            name=name,
            vendor=vendor,
            device_type=device_type,
            memory_mb=memory_mb,
            max_threads=max_threads,
            max_slots=max(0, max_slots),
            pci_vendor_id=pci_vendor_id,
        )

    def _run(self, command: str) -> str:
        try:
            output = subprocess.check_output(shlex.split(command), stderr=subprocess.DEVNULL, text=True)
            return output.strip()
        except Exception as exc:
            logger.debug("Device probe command failed (%s): %s", command, exc)
            return ""

    def _detect_vulkan(self) -> list[DetectedDevice]:
        if not is_supported_vendor("vulkan"):
            return []
        try:
            result = subprocess.run(
                ["vulkaninfo"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=15,
            )
            output = result.stdout
        except Exception as exc:
            logger.debug("Device probe command failed (vulkaninfo): %s", exc)
            return []
        if not output:
            return []

        devices: list[DetectedDevice] = []
        amd_vulkan_indices: list[int] = []
        amd_vulkan_by_idx: dict[int, str] = {}
        amd_integrated_by_idx: dict[int, bool] = {}
        blocks = re.split(r"GPU(\d+):", output)
        i = 1
        while i + 1 < len(blocks):
            idx = int(blocks[i])
            block = blocks[i + 1]
            i += 2

            name_match = re.search(r"deviceName\s*=\s*(.+)", block)
            type_match = re.search(r"deviceType\s*=\s*(.+)", block)
            if not name_match:
                continue

            name = name_match.group(1).strip()
            device_type_str = type_match.group(1).strip().lower() if type_match else ""
            vendor_id = _parse_vulkan_vendor_id(block)
            pci_bdf = parse_vulkan_pci_bdf(block)
            if "cpu" in device_type_str or "virtual_gpu" in device_type_str:
                continue

            if vendor_id == AMD_VENDOR_ID:
                amd_vulkan_indices.append(idx)
                if pci_bdf:
                    amd_vulkan_by_idx[idx] = pci_bdf
                amd_integrated_by_idx[idx] = is_vulkan_integrated_gpu(device_type_str)

            devices.append(
                DetectedDevice(
                    hardware_id=f"vulkan:{idx}",
                    stable_hardware_id=pci_bdf,
                    stable_hardware_id_source="pci_bdf" if pci_bdf else None,
                    name=name,
                    vendor="vulkan",
                    device_type="gpu",
                    memory_mb=0,
                    pci_vendor_id=vendor_id,
                )
            )

        if devices:
            memory_by_idx = _parse_vulkaninfo_device_local_heap_mb(output)
            memory_by_idx.update(
                self._read_amdgpu_memory_totals(amd_vulkan_indices, amd_vulkan_by_idx, amd_integrated_by_idx)
            )
            for device in devices:
                idx = int(device.hardware_id.split(":")[1])
                device.memory_mb = memory_by_idx.get(idx, 0)

        return devices

    def _read_amdgpu_memory_totals(
        self,
        amd_vulkan_indices: list[int],
        amd_vulkan_by_idx: dict[int, str],
        integrated_by_idx: dict[int, bool] | None = None,
    ) -> dict[int, int]:
        memory_by_idx: dict[int, int] = {}
        if not amd_vulkan_indices:
            return memory_by_idx

        amd_cards_by_bdf = list_amdgpu_cards_by_bdf()
        amd_ordered_paths = list_amdgpu_device_paths()
        for position, vulkan_idx in enumerate(amd_vulkan_indices):
            pci_bdf = amd_vulkan_by_idx.get(vulkan_idx)
            device_path = resolve_amdgpu_device_path(
                pci_bdf,
                position=position,
                cards_by_bdf=amd_cards_by_bdf,
                ordered_paths=amd_ordered_paths,
            )
            if device_path is None:
                continue
            integrated = (integrated_by_idx or {}).get(vulkan_idx, False)
            metrics = read_amdgpu_memory_metrics(device_path, integrated=integrated)
            total_mb = metrics.get("memory_total_mb", 0)
            if total_mb > 0:
                memory_by_idx[vulkan_idx] = total_mb

        return memory_by_idx

    @staticmethod
    def _read_sysfs_int(path: Path) -> int | None:
        try:
            return int(path.read_text().strip())
        except Exception:
            return None

    def _detect_cpu(self) -> list[DetectedDevice]:
        cores = psutil.cpu_count(logical=False) or 1
        threads = psutil.cpu_count(logical=True) or cores
        memory_mb = int(psutil.virtual_memory().total / (1024 * 1024))
        return [
            DetectedDevice(
                hardware_id="cpu:0",
                stable_hardware_id=None,
                stable_hardware_id_source=None,
                name="CPU",
                vendor="cpu",
                device_type="cpu",
                memory_mb=memory_mb,
                max_threads=threads,
                max_slots=0,
            )
        ]

    def _detect_configured_devices(self) -> list[DetectedDevice]:
        vendors = get_supported_vendors()
        settings = get_settings()
        if not settings.supported_device_list():
            return []

        devices: list[DetectedDevice] = []
        cpu_device = self._detect_cpu()[0]
        if "cpu" in vendors:
            devices.append(cpu_device)
        if "vulkan" in vendors:
            devices.append(
                DetectedDevice(
                    hardware_id="vulkan:0",
                    stable_hardware_id=None,
                    stable_hardware_id_source=None,
                    name="Vulkan GPU",
                    vendor="vulkan",
                    device_type="gpu",
                    memory_mb=0,
                    max_slots=0,
                )
            )
        return devices


def _is_vulkan_device_local_heap(heap_block: str) -> bool:
    """True when the heap block is device-local (modern and legacy vulkaninfo flag names)."""
    return "MEMORY_HEAP_DEVICE_LOCAL_BIT" in heap_block


def _parse_vulkaninfo_heap_field_mb(heap_block: str, field: str) -> int | None:
    """Parse a vulkaninfo ``size`` or ``usage`` line from a memory heap block into MiB."""
    match = re.search(rf"\b{field}\s*=\s*([^\n]+)", heap_block, re.IGNORECASE)
    if not match:
        return None

    line = match.group(1)
    human_units = re.findall(r"\(([\d.]+)\s*(GiB|MiB|KiB|bytes|B)\)", line, re.IGNORECASE)
    if human_units:
        value, unit = human_units[-1]
        return _vulkan_size_to_mb(float(value), unit)

    simple = re.match(r"([\d.]+)\s*(MiB|GiB|KiB|bytes|B)?", line.strip(), re.IGNORECASE)
    if not simple:
        return None
    return _vulkan_size_to_mb(float(simple.group(1)), simple.group(2))


def _parse_vulkaninfo_gpu_memory_metrics(output: str) -> dict[int, dict[str, int]]:
    """Parse heap total and usage (MiB) per GPU index from full vulkaninfo text.

    total_mb is the max device-local heap size (physical VRAM). used_mb sums usage
    across all heaps so Intel ANV GTT/system allocations are included.
    """
    memory_by_idx: dict[int, dict[str, int]] = {}
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

        total_mb = 0
        used_mb = 0
        for heap_block in re.split(r"memoryHeaps\[\d+\]:", block)[1:]:
            usage_mb = _parse_vulkaninfo_heap_field_mb(heap_block, "usage")
            if usage_mb is not None:
                used_mb += usage_mb
            if not _is_vulkan_device_local_heap(heap_block):
                continue
            size_mb = _parse_vulkaninfo_heap_field_mb(heap_block, "size")
            if size_mb is not None:
                total_mb = max(total_mb, size_mb)

        if total_mb > 0:
            memory_by_idx[idx] = {"total_mb": total_mb, "used_mb": used_mb}

    return memory_by_idx


def _parse_vulkaninfo_device_local_heap_mb(output: str) -> dict[int, int]:
    """Parse device-local heap total size (MiB) per GPU index from full vulkaninfo text output."""
    return {
        idx: metrics["total_mb"]
        for idx, metrics in _parse_vulkaninfo_gpu_memory_metrics(output).items()
        if metrics["total_mb"] > 0
    }


def _parse_vulkan_vendor_id(block: str) -> int | None:
    match = re.search(r"vendorID\s*=\s*(0x[0-9a-fA-F]+|\d+)", block)
    if not match:
        return None

    raw_value = match.group(1)
    try:
        return int(raw_value, 16 if raw_value.lower().startswith("0x") else 10)
    except ValueError:
        return None


def _vulkan_size_to_mb(value: float, unit: str | None) -> int:
    unit = (unit or "bytes").lower()
    if unit == "mib":
        return int(value)
    if unit == "gib":
        return int(value * 1024)
    if unit == "kib":
        return int(value / 1024)
    if unit in ("bytes", "b"):
        return int(value / (1024 * 1024))
    # Unknown unit — if the value looks like it's already in MiB (< 1 million) keep it,
    # otherwise assume bytes.
    if value < 1_000_000:
        return int(value)
    return int(value / (1024 * 1024))


def build_device_display_suffix(stable_hardware_id: str | None, hardware_id: str) -> str:
    source_value = stable_hardware_id or hardware_id
    compact_value = re.sub(r"[^A-Za-z0-9]", "", source_value)
    suffix = (compact_value or source_value)[-4:].upper()
    return suffix if suffix else "????"


def _normalize_optional_identifier(value: object) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip()
    if not normalized or normalized.upper() in {"N/A", "NONE", "UNKNOWN"}:
        return None

    return normalized


def _normalize_identifier_source(value: object) -> str | None:
    normalized = _normalize_optional_identifier(value)
    return normalized.lower() if normalized else None
