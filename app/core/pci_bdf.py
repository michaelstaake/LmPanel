"""Shared PCI BDF parsing for Vulkan and sysfs device identity."""

from __future__ import annotations

import re


def normalize_pci_bdf(value: str) -> str | None:
    """Normalize PCI BDF strings to ``domain:bus:device.function``."""
    text = value.strip().lower()
    match = re.match(
        r"(?:([0-9a-f]{1,4}):)?([0-9a-f]{2}):([0-9a-f]{2})(?:\.([0-9a-f]))?",
        text,
    )
    if not match:
        return None
    domain = (match.group(1) or "0000").zfill(4)
    function = match.group(4) or "0"
    return f"{domain}:{match.group(2)}:{match.group(3)}.{function}"


def parse_vulkan_pci_bdf(block: str) -> str | None:
    for pattern in (r"pciBusInfo\s*=\s*(\S+)", r"pciBusID\s*=\s*(\S+)"):
        match = re.search(pattern, block)
        if match:
            normalized = normalize_pci_bdf(match.group(1))
            if normalized:
                return normalized
    return None
