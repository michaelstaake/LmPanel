import json
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
    list_amdgpu_device_paths,
    read_amdgpu_memory_metrics,
)
from app.core.config import get_settings
from app.core.gpu_pool_manager import delete_unavailable_devices
from app.models.device import Device

logger = logging.getLogger(__name__)

AMD_VENDOR_ID = 0x1002
INTEL_VENDOR_ID = 0x8086


def get_supported_vendors() -> set[str]:
    settings = get_settings()
    configured = settings.supported_device_list()
    if configured:
        return set(configured)

    return {"cpu", "nvidia", "vulkan", "rocm"}


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
        hide_vulkan_amd = self._should_hide_vulkan_amd()
        devices.extend(self._detect_nvidia())
        devices.extend(self._detect_rocm())
        devices.extend(self._detect_vulkan(exclude_amd=hide_vulkan_amd))
        devices.extend(self._detect_cpu())
        return devices

    def _should_hide_vulkan_amd(self) -> bool:
        if not is_supported_vendor("rocm"):
            return False

        settings = get_settings()
        runtime_map = settings.inference_runtime_url_map()
        rocm_url = runtime_map.get("rocm")
        if not rocm_url:
            return len(self._detect_rocm()) > 0

        timeout = settings.inference_service_timeout_seconds
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.get(f"{rocm_url}/health")
                response.raise_for_status()
        except Exception:
            return False

        return True

    def default_name_for_device(self, device: Device) -> str:
        cached = getattr(self, "_default_names_by_hardware_id", {}).get(device.hardware_id)
        if cached:
            return cached

        for detected in self.detect_all():
            if detected.hardware_id == device.hardware_id:
                return detected.name

        return device.name

    def sync_detected_devices(self, db: Session, *, auto_enable_defaults: bool = False) -> list[Device]:
        detected = self.detect_all()
        self._default_names_by_hardware_id = {item.hardware_id: item.name for item in detected}
        existing = {d.hardware_id: d for d in db.query(Device).all()}
        detected_ids = {device.hardware_id for device in detected}
        gpu_detected = any(device.device_type == "gpu" and device.vendor != "cpu" for device in detected)

        removed_device_ids = delete_unavailable_devices(db, detected_ids)
        if removed_device_ids:
            logger.info(
                "Removed %s device(s) no longer reported by active runtimes: %s",
                len(removed_device_ids),
                removed_device_ids,
            )
            existing = {d.hardware_id: d for d in db.query(Device).all()}

        for d in detected:
            row = existing.get(d.hardware_id)
            enabled = self._should_auto_enable(d, gpu_detected) if auto_enable_defaults else False
            if row is None:
                row = Device(
                    hardware_id=d.hardware_id,
                    stable_hardware_id=d.stable_hardware_id,
                    stable_hardware_id_source=d.stable_hardware_id_source,
                    name=d.name,
                    vendor=d.vendor,
                    device_type=d.device_type,
                    memory_mb=d.memory_mb,
                    enabled=enabled,
                    max_threads=d.max_threads,
                    max_slots=d.max_slots,
                )
                db.add(row)
            else:
                row.stable_hardware_id = d.stable_hardware_id
                row.stable_hardware_id_source = d.stable_hardware_id_source
                if row.name == d.name:
                    row.name = d.name
                row.vendor = d.vendor
                row.device_type = d.device_type
                row.memory_mb = d.memory_mb
                if row.device_type == "cpu":
                    row.max_threads = d.max_threads or row.max_threads
                    row.max_slots = max(0, d.max_slots)

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
        rocm_runtime_ok = False

        for runtime_vendor, base_url in runtime_map.items():
            try:
                with httpx.Client(timeout=timeout) as client:
                    response = client.get(f"{base_url}/runtime/devices")
                    response.raise_for_status()
            except Exception as exc:
                logger.warning("Failed to fetch devices from runtime %s at %s: %s", runtime_vendor, base_url, exc)
                continue

            if runtime_vendor == "rocm":
                rocm_runtime_ok = True

            payload = response.json()
            rows = payload.get("devices", []) if isinstance(payload, dict) else []
            for row in rows:
                device = self._parse_runtime_device(row)
                if not device:
                    continue
                if runtime_vendor != "default" and device.vendor != runtime_vendor:
                    continue
                if rocm_runtime_ok and device.vendor == "vulkan" and device.pci_vendor_id == AMD_VENDOR_ID:
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

    def _detect_rocm(self) -> list[DetectedDevice]:
        if not is_supported_vendor("rocm"):
            return []

        json_output = self._run("rocm-smi --showproductname --showmeminfo vram --json")
        devices = self._parse_rocm_json(json_output)
        if devices:
            self._attach_rocm_pci_bdfs(devices)
            self._apply_amdgpu_sysfs_memory_totals(devices)
            return devices

        text_devices = self._parse_rocm_text(self._run("rocm-smi --showproductname --showmeminfo vram"))
        self._attach_rocm_pci_bdfs(text_devices)
        self._apply_amdgpu_sysfs_memory_totals(text_devices)
        return text_devices

    @staticmethod
    def _parse_rocm_json(json_output: str) -> list[DetectedDevice]:
        if not json_output:
            return []
        try:
            data = json.loads(json_output)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, dict):
            return []

        devices: list[DetectedDevice] = []
        for card_key in sorted(data.keys()):
            if not card_key.lower().startswith("card"):
                continue
            entry = data[card_key]
            if not isinstance(entry, dict):
                continue

            digits = re.sub(r"\D", "", card_key) or str(len(devices))
            index = int(digits)

            name = (
                entry.get("Card series")
                or entry.get("Card Series")
                or entry.get("Card model")
                or entry.get("Card Model")
                or f"AMD GPU {index}"
            )

            memory_bytes = 0
            for key, value in entry.items():
                if "vram total memory" in key.lower():
                    try:
                        memory_bytes = int(str(value).strip())
                    except (TypeError, ValueError):
                        memory_bytes = 0
                    break

            devices.append(
                DetectedDevice(
                    hardware_id=f"rocm:{index}",
                    stable_hardware_id=None,
                    stable_hardware_id_source=None,
                    name=str(name)[:120],
                    vendor="rocm",
                    device_type="gpu",
                    memory_mb=int(memory_bytes / (1024 * 1024)) if memory_bytes else 0,
                    max_slots=0,
                )
            )
        return devices

    @staticmethod
    def _parse_rocm_text(text_output: str) -> list[DetectedDevice]:
        if not text_output:
            return []
        devices: list[DetectedDevice] = []
        for line in text_output.splitlines():
            if "vram total memory" not in line.lower():
                continue
            card_match = re.search(r"card(\d+)", line, re.IGNORECASE)
            size_match = re.search(r"(\d+(?:\.\d+)?)\s*(b|kb|mb|gb|tb)?", line, re.IGNORECASE)
            if not card_match or not size_match:
                continue
            index = int(card_match.group(1))
            value = float(size_match.group(1))
            unit = (size_match.group(2) or "b").lower()
            multipliers = {"b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3, "tb": 1024**4}
            memory_bytes = int(value * multipliers.get(unit, 1))
            devices.append(
                DetectedDevice(
                    hardware_id=f"rocm:{index}",
                    stable_hardware_id=None,
                    stable_hardware_id_source=None,
                    name=f"AMD GPU {index}",
                    vendor="rocm",
                    device_type="gpu",
                    memory_mb=int(memory_bytes / (1024 * 1024)),
                    max_slots=0,
                )
            )
        return devices

    def _attach_rocm_pci_bdfs(self, devices: list[DetectedDevice]) -> None:
        pci_bdfs = _read_amdgpu_pci_bdfs()
        for device, pci_bdf in zip(devices, pci_bdfs, strict=False):
            device.stable_hardware_id = pci_bdf
            device.stable_hardware_id_source = "pci_bdf"

    def _run(self, command: str) -> str:
        try:
            output = subprocess.check_output(shlex.split(command), stderr=subprocess.DEVNULL, text=True)
            return output.strip()
        except Exception as exc:
            logger.debug("Device probe command failed (%s): %s", command, exc)
            return ""

    def _detect_nvidia(self) -> list[DetectedDevice]:
        output = self._run("nvidia-smi --query-gpu=index,gpu_uuid,name,memory.total --format=csv,noheader,nounits")
        devices: list[DetectedDevice] = []
        for line in output.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 4:
                continue
            stable_hardware_id = _normalize_optional_identifier(parts[1])
            devices.append(
                DetectedDevice(
                    hardware_id=f"nvidia:{parts[0]}",
                    stable_hardware_id=stable_hardware_id,
                    stable_hardware_id_source="nvidia_uuid" if stable_hardware_id else None,
                    name=parts[2],
                    vendor="nvidia",
                    device_type="gpu",
                    memory_mb=int(parts[3] or "0"),
                    max_slots=0,
                )
            )
        return devices

    def _detect_vulkan(self, *, exclude_amd: bool = False) -> list[DetectedDevice]:
        if not is_supported_vendor("vulkan"):
            return []
        try:
            result = subprocess.run(
                ["vulkaninfo", "--summary"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            output = result.stdout.strip()
        except Exception as exc:
            logger.debug("Device probe command failed (vulkaninfo --summary): %s", exc)
            return []
        if not output:
            return []
        devices: list[DetectedDevice] = []
        amd_vulkan_indices: list[int] = []
        amd_integrated_by_idx: dict[int, bool] = {}
        # vulkaninfo --summary groups each physical device under a "GPU<N>:" header
        blocks = re.split(r"GPU(\d+):", output)
        # blocks layout: [preamble, idx0, block0, idx1, block1, ...]
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
            # Skip software/CPU renderers (e.g. lavapipe, llvmpipe)
            if "cpu" in device_type_str or "virtual_gpu" in device_type_str:
                continue

            if vendor_id == AMD_VENDOR_ID:
                amd_vulkan_indices.append(idx)
                amd_integrated_by_idx[idx] = is_vulkan_integrated_gpu(device_type_str)
                if exclude_amd:
                    continue

            devices.append(
                DetectedDevice(
                    hardware_id=f"vulkan:{idx}",
                    stable_hardware_id=None,
                    stable_hardware_id_source=None,
                    name=name,
                    vendor="vulkan",
                    device_type="gpu",
                    memory_mb=0,
                    pci_vendor_id=vendor_id,
                )
            )

        if devices:
            memory_by_idx = self._parse_vulkan_device_memory()
            memory_by_idx.update(self._read_amdgpu_memory_totals(amd_vulkan_indices, amd_integrated_by_idx))
            for device in devices:
                idx = int(device.hardware_id.split(":")[1])
                device.memory_mb = memory_by_idx.get(idx, 0)

        return devices

    def _parse_vulkan_device_memory(self) -> dict[int, int]:
        """Return vulkan device index -> device-local memory total (MiB) from full vulkaninfo output."""
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
            logger.debug("vulkaninfo full output failed: %s", exc)
            return {}
        return _parse_vulkaninfo_device_local_heap_mb(output)

    def _read_amdgpu_memory_totals(
        self,
        amd_vulkan_indices: list[int],
        integrated_by_idx: dict[int, bool] | None = None,
    ) -> dict[int, int]:
        memory_by_idx: dict[int, int] = {}
        if not amd_vulkan_indices:
            return memory_by_idx

        amd_card_paths = list_amdgpu_device_paths()
        for vulkan_idx, device_path in zip(amd_vulkan_indices, amd_card_paths, strict=False):
            integrated = (integrated_by_idx or {}).get(vulkan_idx, False)
            metrics = read_amdgpu_memory_metrics(device_path, integrated=integrated)
            total_mb = metrics.get("memory_total_mb", 0)
            if total_mb > 0:
                memory_by_idx[vulkan_idx] = total_mb

        return memory_by_idx

    def _apply_amdgpu_sysfs_memory_totals(self, devices: list[DetectedDevice]) -> None:
        amd_card_paths = list_amdgpu_device_paths()
        for device, device_path in zip(devices, amd_card_paths, strict=False):
            metrics = read_amdgpu_memory_metrics(device_path, integrated=False)
            total_mb = metrics.get("memory_total_mb")
            if total_mb:
                device.memory_mb = total_mb

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
        if "nvidia" in vendors:
            devices.append(
                DetectedDevice(
                    hardware_id="nvidia:0",
                    stable_hardware_id=None,
                    stable_hardware_id_source=None,
                    name="NVIDIA GPU",
                    vendor="nvidia",
                    device_type="gpu",
                    memory_mb=0,
                    max_slots=0,
                )
            )
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
        if "rocm" in vendors:
            devices.append(
                DetectedDevice(
                    hardware_id="rocm:0",
                    stable_hardware_id=None,
                    stable_hardware_id_source=None,
                    name="ROCm GPU",
                    vendor="rocm",
                    device_type="gpu",
                    memory_mb=0,
                    max_slots=0,
                )
            )
        return devices


def _read_amdgpu_pci_bdfs() -> list[str]:
    bdfs: list[str] = []
    try:
        card_paths = sorted(
            p.parent for p in Path("/sys/class/drm").glob("card*/device/gpu_busy_percent") if p.is_file()
        )
    except Exception:
        return bdfs

    for device_path in card_paths:
        uevent_path = device_path / "uevent"
        try:
            uevent = uevent_path.read_text()
        except Exception:
            continue
        match = re.search(r"PCI_SLOT_NAME=(\S+)", uevent)
        if match:
            bdfs.append(match.group(1))
    return bdfs


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
