import unittest

from app.core.gpu_chip_vendor import (
    AMD_VENDOR_ID,
    INTEL_VENDOR_ID,
    chip_vendor_key,
    chip_vendor_label,
    normalize_pci_vendor_id,
)


class GpuChipVendorTests(unittest.TestCase):
    def test_chip_vendor_label(self) -> None:
        self.assertEqual(chip_vendor_label(AMD_VENDOR_ID), "AMD")
        self.assertEqual(chip_vendor_label(INTEL_VENDOR_ID), "Intel")
        self.assertIsNone(chip_vendor_label(0x10DE))
        self.assertIsNone(chip_vendor_label(0x1234))

    def test_chip_vendor_key(self) -> None:
        self.assertEqual(chip_vendor_key(AMD_VENDOR_ID), "amd")
        self.assertEqual(chip_vendor_key(INTEL_VENDOR_ID), "intel")
        self.assertIsNone(chip_vendor_key(0x10DE))
        self.assertIsNone(chip_vendor_key(None))

    def test_normalize_pci_vendor_id(self) -> None:
        self.assertEqual(normalize_pci_vendor_id(AMD_VENDOR_ID), AMD_VENDOR_ID)
        self.assertIsNone(normalize_pci_vendor_id(0x10DE))
        self.assertIsNone(normalize_pci_vendor_id("not-a-number"))


if __name__ == "__main__":
    unittest.main()
