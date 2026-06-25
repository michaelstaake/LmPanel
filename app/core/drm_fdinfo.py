"""Shared DRM /proc fdinfo VRAM parsing (Intel, AMD, and other DRM drivers)."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.pci_bdf import normalize_pci_bdf


def parse_fdinfo_drm_size_bytes(value: str) -> int:
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


def _pdev_matches(file_pdev: str | None, pci_bdf: str) -> bool:
    if not file_pdev:
        return False
    normalized_file = normalize_pci_bdf(file_pdev)
    normalized_target = normalize_pci_bdf(pci_bdf)
    return normalized_file is not None and normalized_file == normalized_target


def collect_fdinfo_vram_by_client(pci_bdf: str) -> dict[tuple[int, int], int]:
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
                vram_bytes = parse_fdinfo_drm_size_bytes(line.split(":", 1)[1])

        if not _pdev_matches(file_pdev, pci_bdf) or client_id is None or vram_bytes <= 0:
            continue
        key = (pid, client_id)
        clients[key] = max(clients.get(key, 0), vram_bytes)

    return clients


def sum_fdinfo_vram_bytes(pci_bdf: str) -> int:
    return sum(collect_fdinfo_vram_by_client(pci_bdf).values())


def fdinfo_vram_mb_by_pid(pci_bdf: str) -> dict[int, int]:
    per_pid: dict[int, int] = {}
    for (pid, _client_id), vram_bytes in collect_fdinfo_vram_by_client(pci_bdf).items():
        per_pid[pid] = per_pid.get(pid, 0) + vram_bytes
    return {pid: int(bytes_val / (1024 * 1024)) for pid, bytes_val in per_pid.items()}
