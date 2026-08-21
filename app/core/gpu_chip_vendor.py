"""PCI GPU chip vendor helpers (AMD, Intel)."""

from __future__ import annotations

AMD_VENDOR_ID = 0x1002
INTEL_VENDOR_ID = 0x8086

KNOWN_GPU_VENDOR_IDS: frozenset[int] = frozenset({AMD_VENDOR_ID, INTEL_VENDOR_ID})


def chip_vendor_label(pci_vendor_id: int | None) -> str | None:
    if pci_vendor_id == AMD_VENDOR_ID:
        return "AMD"
    if pci_vendor_id == INTEL_VENDOR_ID:
        return "Intel"
    return None


def chip_vendor_key(pci_vendor_id: int | None) -> str | None:
    if pci_vendor_id == AMD_VENDOR_ID:
        return "amd"
    if pci_vendor_id == INTEL_VENDOR_ID:
        return "intel"
    return None


def normalize_pci_vendor_id(value: object) -> int | None:
    if value is None:
        return None
    try:
        vendor_id = int(value)
    except (TypeError, ValueError):
        return None
    return vendor_id if vendor_id in KNOWN_GPU_VENDOR_IDS else None
