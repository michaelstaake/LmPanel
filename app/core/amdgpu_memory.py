"""AMD GPU memory metrics via amdgpu sysfs (VRAM + GTT for integrated/APU GPUs)."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.pci_bdf import normalize_pci_bdf

APU_VRAM_THRESHOLD_MB = 4096


def _read_sysfs_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except Exception:
        return None


def parse_vulkan_device_type(block: str) -> str:
    match = re.search(r"deviceType\s*=\s*(.+)", block)
    return match.group(1).strip().lower() if match else ""


def is_vulkan_integrated_gpu(device_type: str) -> bool:
    return "integrated" in device_type


def should_include_gtt(
    vram_total_bytes: int,
    gtt_total_bytes: int | None,
    *,
    integrated: bool,
) -> bool:
    if gtt_total_bytes is None or gtt_total_bytes <= 0:
        return False
    if integrated:
        return True

    vram_mb = vram_total_bytes / (1024 * 1024)
    gtt_mb = gtt_total_bytes / (1024 * 1024)
    return vram_mb <= APU_VRAM_THRESHOLD_MB and gtt_mb >= vram_mb


def read_amdgpu_memory_metrics(device_path: Path, *, integrated: bool = False) -> dict:
    """Read amdgpu VRAM/GTT sysfs counters and return memory totals in MiB."""
    vram_total = _read_sysfs_int(device_path / "mem_info_vram_total")
    vram_used = _read_sysfs_int(device_path / "mem_info_vram_used")
    gtt_total = _read_sysfs_int(device_path / "mem_info_gtt_total")
    gtt_used = _read_sysfs_int(device_path / "mem_info_gtt_used")

    include_gtt = should_include_gtt(vram_total or 0, gtt_total, integrated=integrated)

    total_bytes = vram_total or 0
    used_bytes = vram_used or 0
    if include_gtt:
        total_bytes += gtt_total or 0
        used_bytes += gtt_used or 0

    result: dict = {}
    if total_bytes > 0:
        result["memory_total_mb"] = int(total_bytes / (1024 * 1024))
    if vram_used is not None or (include_gtt and gtt_used is not None):
        result["memory_used_mb"] = int(used_bytes / (1024 * 1024))
    if total_bytes > 0 or vram_used is not None or gtt_used is not None:
        result["memory_source"] = "sysfs-gtt" if include_gtt else "sysfs"
    return result


def list_amdgpu_device_paths() -> list[Path]:
    try:
        return sorted(
            p.parent for p in Path("/sys/class/drm").glob("card*/device/gpu_busy_percent") if p.is_file()
        )
    except Exception:
        return []


def list_amdgpu_cards_by_bdf() -> dict[str, Path]:
    """Map PCI BDF to ``/sys/class/drm/card*/device`` for amdgpu GPUs."""
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
        if driver != "amdgpu":
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
            cards[bdf] = device
    return cards
