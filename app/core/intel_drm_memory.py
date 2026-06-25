"""Intel GPU VRAM metrics via DRM xe ioctl and /proc fdinfo (matches nvtop)."""

from __future__ import annotations

import ctypes
import logging
import os
import re
import struct
from pathlib import Path

from app.core.pci_bdf import normalize_pci_bdf, parse_vulkan_pci_bdf

logger = logging.getLogger(__name__)

DRM_COMMAND_BASE = 0x40
DRM_XE_DEVICE_QUERY = 0x00
DRM_XE_DEVICE_QUERY_MEM_REGIONS = 1
DRM_XE_MEM_REGION_CLASS_VRAM = 1

_DRM_XE_MEM_REGION_FORMAT = "<HHI" + ("Q" * 10)
_DRM_XE_MEM_REGION_SIZE = struct.calcsize(_DRM_XE_MEM_REGION_FORMAT)


class _DrmXeDeviceQuery(ctypes.Structure):
    _fields_ = [
        ("extensions", ctypes.c_uint64),
        ("query", ctypes.c_uint32),
        ("size", ctypes.c_uint32),
        ("data", ctypes.c_uint64),
    ]


def _drm_ioctl_iowr(nr: int, struct_size: int) -> int:
    ioc_readwrite = 3
    return (ioc_readwrite << 30) | (struct_size << 16) | (ord("d") << 8) | nr


_DRM_IOCTL_XE_DEVICE_QUERY = _drm_ioctl_iowr(
    DRM_COMMAND_BASE + DRM_XE_DEVICE_QUERY,
    ctypes.sizeof(_DrmXeDeviceQuery),
)


def list_intel_drm_cards_by_bdf() -> dict[str, Path]:
    """Map PCI BDF to ``/dev/dri/cardN`` for Intel ``xe``/``i915`` drivers."""
    cards: dict[str, Path] = {}
    try:
        card_dirs = sorted(Path("/sys/class/drm").glob("card[0-9]*"))
    except Exception:
        return cards

    for card_sysfs in card_dirs:
        if not card_sysfs.is_dir() or "-" in card_sysfs.name:
            continue
        device = card_sysfs / "device"
        try:
            driver = (device / "driver").resolve().name
        except Exception:
            continue
        if driver not in ("xe", "i915"):
            continue
        try:
            uevent = (device / "uevent").read_text()
        except Exception:
            continue
        match = re.search(r"PCI_SLOT_NAME=(\S+)", uevent)
        if not match:
            continue
        bdf = normalize_pci_bdf(match.group(1))
        if bdf:
            cards[bdf] = Path("/dev/dri") / card_sysfs.name
    return cards


def _query_xe_vram_bytes(card_path: Path) -> tuple[int | None, int | None]:
    """Return (total_bytes, used_bytes) for the VRAM region via DRM xe ioctl."""
    try:
        import fcntl
    except ImportError:
        return None, None

    try:
        fd = os.open(str(card_path), os.O_RDONLY)
    except OSError as exc:
        logger.debug("Could not open %s for xe memory query: %s", card_path, exc)
        return None, None

    try:
        query = _DrmXeDeviceQuery(0, DRM_XE_DEVICE_QUERY_MEM_REGIONS, 0, 0)
        fcntl.ioctl(fd, _DRM_IOCTL_XE_DEVICE_QUERY, query)
        bufsize = int(query.size)
        if bufsize <= 0:
            return None, None

        buffer = ctypes.create_string_buffer(bufsize)
        query.data = ctypes.addressof(buffer)
        query.size = bufsize
        fcntl.ioctl(fd, _DRM_IOCTL_XE_DEVICE_QUERY, query)

        num_regions, _pad = struct.unpack_from("<II", buffer.raw, 0)
        offset = 8
        total_bytes: int | None = None
        used_bytes: int | None = None
        first_region: tuple[int, int, int] | None = None

        for _ in range(num_regions):
            if offset + _DRM_XE_MEM_REGION_SIZE > bufsize:
                break
            unpacked = struct.unpack_from(_DRM_XE_MEM_REGION_FORMAT, buffer.raw, offset)
            offset += _DRM_XE_MEM_REGION_SIZE
            mem_class = unpacked[0]
            region_total = unpacked[3]
            region_used = unpacked[4]
            if first_region is None:
                first_region = (mem_class, region_total, region_used)

            if mem_class == DRM_XE_MEM_REGION_CLASS_VRAM or num_regions == 1:
                total_bytes = region_total
                if region_used != 0:
                    used_bytes = region_used
                if mem_class == DRM_XE_MEM_REGION_CLASS_VRAM:
                    break

        if total_bytes is None and first_region is not None:
            total_bytes = first_region[1]
            if first_region[2] != 0:
                used_bytes = first_region[2]

        return total_bytes, used_bytes
    except OSError as exc:
        logger.debug("xe DRM memory query failed for %s: %s", card_path, exc)
        return None, None
    finally:
        os.close(fd)


def _parse_fdinfo_drm_size_bytes(value: str) -> int:
    match = re.search(r"(\d+)\s*(kB|KiB|MB|MiB|GB|GiB)?", value.strip(), re.IGNORECASE)
    if not match:
        return 0
    amount = int(match.group(1))
    unit = (match.group(2) or "kib").lower()
    if unit in ("kb", "kib"):
        return amount * 1024
    if unit in ("mb", "mib"):
        return amount * 1024 * 1024
    if unit in ("gb", "gib"):
        return amount * 1024 * 1024 * 1024
    return amount


def _collect_fdinfo_vram_by_client(pdev: str) -> dict[tuple[int, int], int]:
    """Sum ``drm-total-vram0`` per (pid, drm-client-id), deduped like nvtop."""
    clients: dict[tuple[int, int], int] = {}
    try:
        fdinfo_paths = list(Path("/proc").glob("[0-9]*/fdinfo/*"))
    except Exception:
        return clients

    for fdinfo_path in fdinfo_paths:
        try:
            pid = int(fdinfo_path.parent.parent.name)
            text = fdinfo_path.read_text()
        except Exception:
            continue

        file_pdev: str | None = None
        client_id: int | None = None
        vram_bytes = 0
        for line in text.splitlines():
            if line.startswith("drm-pdev:"):
                file_pdev = line.split(":", 1)[1].strip()
            elif line.startswith("drm-client-id:"):
                try:
                    client_id = int(line.split(":", 1)[1].strip())
                except ValueError:
                    client_id = None
            elif line.startswith("drm-total-vram0:"):
                vram_bytes = _parse_fdinfo_drm_size_bytes(line.split(":", 1)[1])

        if file_pdev != pdev or client_id is None or vram_bytes <= 0:
            continue
        key = (pid, client_id)
        clients[key] = max(clients.get(key, 0), vram_bytes)

    return clients


def sum_fdinfo_vram_bytes(pdev: str) -> int:
    return sum(_collect_fdinfo_vram_by_client(pdev).values())


def fdinfo_vram_mb_by_pid(pdev: str) -> dict[int, int]:
    per_pid: dict[int, int] = {}
    for (pid, _client_id), vram_bytes in _collect_fdinfo_vram_by_client(pdev).items():
        per_pid[pid] = per_pid.get(pid, 0) + vram_bytes
    return {pid: int(bytes_val / (1024 * 1024)) for pid, bytes_val in per_pid.items()}


def read_intel_vram_metrics(pci_bdf: str) -> dict[str, object]:
    """VRAM total/used (MiB) and per-pid usage for an Intel GPU at ``pci_bdf``."""
    cards = list_intel_drm_cards_by_bdf()
    card_path = cards.get(pci_bdf)
    if card_path is None:
        return {}

    driver = "unknown"
    try:
        card_sysfs = Path("/sys/class/drm") / card_path.name / "device" / "driver"
        driver = card_sysfs.resolve().name
    except Exception:
        pass

    total_bytes: int | None = None
    used_bytes: int | None = None
    if driver == "xe":
        total_bytes, used_bytes = _query_xe_vram_bytes(card_path)

    fdinfo_by_pid = fdinfo_vram_mb_by_pid(pci_bdf)
    fdinfo_total_bytes = sum_fdinfo_vram_bytes(pci_bdf)

    memory_source = "vulkaninfo"
    if (used_bytes is None or used_bytes == 0) and fdinfo_total_bytes > 0:
        used_bytes = fdinfo_total_bytes
        memory_source = "fdinfo"
    elif used_bytes and used_bytes > 0 and driver == "xe":
        memory_source = "drm-xe"

    result: dict[str, object] = {
        "memory_source": memory_source,
        "process_memory_by_pid": fdinfo_by_pid,
    }
    if total_bytes is not None and total_bytes > 0:
        result["memory_total_mb"] = int(total_bytes / (1024 * 1024))
    if used_bytes is not None and used_bytes >= 0:
        result["memory_used_mb"] = int(used_bytes / (1024 * 1024))

    return result
