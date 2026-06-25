"""NVIDIA GPU memory metrics via nvidia-smi (used when Vulkan reports inaccurate usage)."""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path

from app.core.pci_bdf import normalize_pci_bdf

logger = logging.getLogger(__name__)


def list_nvidia_device_paths() -> list[Path]:
    """Return sysfs device paths for GPUs using the nvidia DRM driver."""
    paths: list[Path] = []
    try:
        card_dirs = sorted(Path("/sys/class/drm").glob("card[0-9]*"))
    except Exception:
        return paths

    for card_sysfs in card_dirs:
        if not card_sysfs.is_dir() or "-" in card_sysfs.name:
            continue
        device = card_sysfs / "device"
        try:
            driver = (device / "driver").resolve().name
        except Exception:
            continue
        if driver != "nvidia":
            continue
        paths.append(device)
    return paths


def list_nvidia_cards_by_bdf() -> dict[str, Path]:
    """Map PCI BDF to /sys/class/drm/card*/device for NVIDIA GPUs."""
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
        if driver != "nvidia":
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


def nvidia_smi_available() -> bool:
    """Check whether nvidia-smi is on the PATH."""
    try:
        result = subprocess.run(
            ["nvidia-smi"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def nvidia_smi_gpu_count() -> int:
    """Return the number of GPUs reported by nvidia-smi."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--list-gpus"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return 0
        lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
        return len(lines)
    except Exception:
        return 0


def nvidia_smi_bdf_by_index() -> dict[int, str]:
    """Map nvidia-smi GPU index to normalized PCI BDF."""
    bdfs: dict[int, str] = {}
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=pci.bus_id", "--format=csv,noheader"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return bdfs
        for idx, line in enumerate(result.stdout.strip().splitlines()):
            normalized = normalize_pci_bdf(line.strip())
            if normalized:
                bdfs[idx] = normalized
    except Exception:
        pass
    return bdfs


def read_nvidia_memory_metrics(gpu_index: int) -> dict:
    """Read memory.total and memory.used from nvidia-smi for a specific GPU index.

    Returns a dict with ``memory_total_mb``, ``memory_used_mb``, and ``memory_source``.
    """
    result: dict = {}
    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=memory.total,memory.used",
                "--format=csv,noheader,nounits",
                "-i", str(gpu_index),
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        ).strip()
    except Exception as exc:
        logger.debug("nvidia-smi query failed for GPU %d: %s", gpu_index, exc)
        return result

    parts = [p.strip() for p in output.split(",")]
    if len(parts) < 2:
        return result

    try:
        total_mb = int(parts[0])
        used_mb = int(parts[1])
    except ValueError:
        return result

    if total_mb > 0:
        result["memory_total_mb"] = total_mb
    if used_mb >= 0:
        result["memory_used_mb"] = used_mb
    result["memory_source"] = "nvidia-smi"
    return result


def read_nvidia_gpu_usage(gpu_index: int) -> int | None:
    """Read GPU utilization percentage from nvidia-smi for a specific GPU index."""
    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu",
                "--format=csv,noheader,nounits",
                "-i", str(gpu_index),
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        ).strip()
    except Exception:
        return None

    try:
        return int(output)
    except ValueError:
        return None


def map_vulkan_index_to_nvidia_index(
    vulkan_pci_bdf: str,
    nvidia_bdf_by_index: dict[int, str],
) -> int | None:
    """Find the nvidia-smi GPU index that matches a Vulkan GPU's PCI BDF."""
    normalized = normalize_pci_bdf(vulkan_pci_bdf)
    if not normalized:
        return None
    for nvidia_idx, bdf in nvidia_bdf_by_index.items():
        if bdf == normalized:
            return nvidia_idx
    return None
