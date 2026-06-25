import unittest
from pathlib import Path

from app.core.drm_fdinfo import (
    fdinfo_vram_mb_by_pid,
    parse_fdinfo_drm_size_bytes,
    sum_fdinfo_vram_bytes,
)
from app.core.pci_bdf import normalize_pci_bdf, parse_vulkan_pci_bdf


class IntelDrmMemoryTests(unittest.TestCase):
    def test_normalize_pci_bdf_with_domain(self) -> None:
        self.assertEqual(normalize_pci_bdf("0000:03:00.0"), "0000:03:00.0")

    def test_normalize_pci_bdf_without_domain(self) -> None:
        self.assertEqual(normalize_pci_bdf("03:00.0"), "0000:03:00.0")

    def test_parse_vulkan_pci_bdf(self) -> None:
        block = "pciBusInfo = 0000:86:00.0\n"
        self.assertEqual(parse_vulkan_pci_bdf(block), "0000:86:00.0")

    def test_parse_vulkan_pci_bdf_component_fields(self) -> None:
        block = """
        domainNumber = 0
        busNumber = 0x03
        deviceNumber = 0x00
        functionNumber = 0x0
        """
        self.assertEqual(parse_vulkan_pci_bdf(block), "0000:03:00.0")

    def test_parse_fdinfo_drm_size_kib(self) -> None:
        self.assertEqual(parse_fdinfo_drm_size_bytes("23992 KiB"), 23992 * 1024)

    def test_sum_fdinfo_vram_dedupes_clients(self) -> None:
        from unittest.mock import patch

        pdev = "0000:03:00.0"

        fdinfo_a = (
            "drm-driver: xe\n"
            f"drm-pdev: {pdev}\n"
            "drm-client-id: 3\n"
            "drm-total-vram0: 2048 KiB\n"
        )
        fdinfo_b = (
            "drm-driver: xe\n"
            f"drm-pdev: {pdev}\n"
            "drm-client-id: 3\n"
            "drm-total-vram0: 512 KiB\n"
        )
        fdinfo_other = (
            "drm-driver: xe\n"
            "drm-pdev: 0000:04:00.0\n"
            "drm-client-id: 9\n"
            "drm-total-vram0: 999 KiB\n"
        )

        class FakeFdinfo:
            def __init__(self, content: str, pid: str = "1234") -> None:
                self.content = content
                self.parent = type("P", (), {"parent": type("PP", (), {"name": pid})()})()

            def read_text(self) -> str:
                return self.content

        fake_paths = [FakeFdinfo(fdinfo_a), FakeFdinfo(fdinfo_b), FakeFdinfo(fdinfo_other)]
        mock_proc = type("Proc", (), {"glob": lambda _self, _pat: fake_paths})()

        with patch("app.core.drm_fdinfo.Path", side_effect=lambda value: mock_proc if value == "/proc" else Path(value)):
            total = sum_fdinfo_vram_bytes(pdev)
            by_pid = fdinfo_vram_mb_by_pid(pdev)

        self.assertEqual(total, 2048 * 1024)
        self.assertEqual(by_pid[1234], 2)


if __name__ == "__main__":
    unittest.main()
