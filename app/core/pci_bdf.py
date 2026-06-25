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


def _parse_vulkan_number(value: str) -> int:
    text = value.strip().lower()
    if text.startswith("0x"):
        return int(text, 16)
    return int(text, 10)


def parse_vulkan_pci_bdf(block: str) -> str | None:
    for pattern in (r"pciBusInfo\s*=\s*(\S+)", r"pciBusID\s*=\s*(\S+)"):
        match = re.search(pattern, block)
        if not match:
            continue
        token = match.group(1).strip()
        if token.endswith(":"):
            continue
        normalized = normalize_pci_bdf(token)
        if normalized:
            return normalized

    domain_match = re.search(r"domainNumber\s*=\s*(?:0x)?([0-9a-f]+)", block, re.IGNORECASE)
    bus_match = re.search(r"busNumber\s*=\s*(?:0x)?([0-9a-f]+)", block, re.IGNORECASE)
    device_match = re.search(r"deviceNumber\s*=\s*(?:0x)?([0-9a-f]+)", block, re.IGNORECASE)
    function_match = re.search(r"functionNumber\s*=\s*(?:0x)?([0-9a-f]+)", block, re.IGNORECASE)
    if bus_match and device_match:
        domain = _parse_vulkan_number(domain_match.group(1)) if domain_match else 0
        bus = _parse_vulkan_number(bus_match.group(1))
        device = _parse_vulkan_number(device_match.group(1))
        function = _parse_vulkan_number(function_match.group(1)) if function_match else 0
        return f"{domain:04x}:{bus:02x}:{device:02x}.{function}"

    return None
