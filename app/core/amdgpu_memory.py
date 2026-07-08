"""AMD GPU memory metrics via amdgpu sysfs (VRAM + GTT for integrated/APU GPUs)."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.pci_bdf import normalize_pci_bdf
from app.core.drm_fdinfo import fdinfo_vram_mb_by_pid

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


def read_amdgpu_gtt_metrics(device_path: Path) -> dict:
    """Read GTT counters separately (used for spillover detection on discrete GPUs)."""
    gtt_total = _read_sysfs_int(device_path / "mem_info_gtt_total")
    gtt_used = _read_sysfs_int(device_path / "mem_info_gtt_used")
    result: dict = {}
    if gtt_total is not None and gtt_total > 0:
        result["gtt_total_mb"] = int(gtt_total / (1024 * 1024))
    if gtt_used is not None:
        result["gtt_used_mb"] = int(gtt_used / (1024 * 1024))
    if result:
        result["gtt_source"] = "sysfs"
    return result


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


def read_amdgpu_gpu_usage(device_path: Path) -> int | None:
    """Read GPU utilization percent from amdgpu sysfs, with mem_busy_percent fallback."""
    for name in ("gpu_busy_percent", "mem_busy_percent"):
        value = _read_sysfs_int(device_path / name)
        if value is not None:
            return min(100, max(0, int(value)))
    return None


def _sysfs_metrics_score(device_path: Path) -> int:
    score = 0
    if (device_path / "gpu_busy_percent").is_file():
        score += 4
    if (device_path / "mem_info_vram_total").is_file():
        score += 2
    if (device_path / "mem_info_vram_used").is_file():
        score += 1
    return score


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
        if not bdf:
            continue
        existing = cards.get(bdf)
        if existing is None or _sysfs_metrics_score(device) > _sysfs_metrics_score(existing):
            cards[bdf] = device
    return cards


def resolve_amdgpu_device_path(
    pci_bdf: str | None,
    *,
    position: int | None = None,
    cards_by_bdf: dict[str, Path] | None = None,
    ordered_paths: list[Path] | None = None,
) -> Path | None:
    """Resolve an amdgpu sysfs device path by PCI BDF, with positional fallback."""
    if cards_by_bdf is None:
        cards_by_bdf = list_amdgpu_cards_by_bdf()
    if ordered_paths is None:
        ordered_paths = list_amdgpu_device_paths()

    if pci_bdf:
        normalized = normalize_pci_bdf(pci_bdf)
        if normalized:
            device_path = cards_by_bdf.get(normalized)
            if device_path is not None and _sysfs_metrics_score(device_path) > 0:
                return device_path

    if position is not None and 0 <= position < len(ordered_paths):
        return ordered_paths[position]
    return None


def apply_amdgpu_live_metrics(
    metric: dict,
    device_path: Path,
    *,
    pci_bdf: str | None = None,
    integrated: bool = False,
) -> None:
    """Merge amdgpu sysfs (and optional fdinfo) counters into a runtime metric dict."""
    usage = read_amdgpu_gpu_usage(device_path)
    if usage is not None:
        metric["usage_percent"] = usage
        metric["usage_source"] = "sysfs"

    gtt = read_amdgpu_gtt_metrics(device_path)
    if gtt.get("gtt_total_mb") is not None:
        metric["gtt_total_mb"] = gtt["gtt_total_mb"]
    if gtt.get("gtt_used_mb") is not None:
        metric["gtt_used_mb"] = gtt["gtt_used_mb"]
    if gtt.get("gtt_source"):
        metric["gtt_source"] = gtt["gtt_source"]

    sysfs = read_amdgpu_memory_metrics(device_path, integrated=integrated)
    if sysfs.get("memory_total_mb"):
        metric["memory_total_mb"] = sysfs["memory_total_mb"]
    sysfs_used = int(sysfs.get("memory_used_mb") or 0)
    used_mb = max(int(metric.get("memory_used_mb") or 0), sysfs_used)
    if sysfs.get("memory_source") and sysfs_used > 0:
        metric["memory_source"] = sysfs["memory_source"]

    if pci_bdf:
        fdinfo_by_pid = fdinfo_vram_mb_by_pid(pci_bdf)
        if fdinfo_by_pid:
            metric["process_memory_by_pid"] = fdinfo_by_pid
            used_mb = max(used_mb, sum(fdinfo_by_pid.values()))

    if used_mb > 0 or sysfs_used > 0:
        metric["memory_used_mb"] = used_mb
