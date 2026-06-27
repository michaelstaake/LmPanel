import os
import unittest

for _env_key in (
    "STARTUP_HEALTHCHECK_INTERVAL",
    "STARTUP_HEALTHCHECK_TIMEOUT",
    "STARTUP_HEALTHCHECK_RETRIES",
    "STARTUP_HEALTHCHECK_START_PERIOD",
    "LLAMA_CPP_TAG",
):
    os.environ.pop(_env_key, None)

from app.core.device_manager import parse_vulkaninfo_bdf_by_index
from app.core.pci_bdf import normalize_pci_bdf, parse_vulkan_pci_bdf


class ParseVulkanPciBdfTests(unittest.TestCase):
    def test_pci_bus_info_string(self) -> None:
        self.assertEqual(parse_vulkan_pci_bdf("pciBusInfo = 0000:03:00.0"), "0000:03:00.0")

    def test_pcibusinfo_ext_decimal_fields(self) -> None:
        # RADV/Mesa style: VkPhysicalDevicePCIBusInfoPropertiesEXT with decimal values.
        block = (
            "VkPhysicalDevicePCIBusInfoPropertiesEXT:\n"
            "\tpciDomain   = 0\n"
            "\tpciBus      = 28\n"
            "\tpciDevice   = 0\n"
            "\tpciFunction = 0\n"
        )
        # 28 decimal == 0x1c
        self.assertEqual(parse_vulkan_pci_bdf(block), "0000:1c:00.0")

    def test_pcibusinfo_ext_high_bus(self) -> None:
        block = "\tpciDomain = 0\n\tpciBus = 105\n\tpciDevice = 0\n\tpciFunction = 0\n"
        self.assertEqual(parse_vulkan_pci_bdf(block), "0000:69:00.0")

    def test_does_not_match_pcibusinfo_prefix_as_decimal(self) -> None:
        # "pciBusInfo = 0000:6c:00.0" must be handled by the string path, not the
        # decimal pciBus path.
        self.assertEqual(parse_vulkan_pci_bdf("pciBusInfo = 0000:6c:00.0"), "0000:6c:00.0")

    def test_legacy_bus_number_fields(self) -> None:
        block = "busNumber = 0x03\ndeviceNumber = 0x00\nfunctionNumber = 0x0\n"
        self.assertEqual(parse_vulkan_pci_bdf(block), "0000:03:00.0")


class ParseVulkaninfoBdfByIndexTests(unittest.TestCase):
    def test_associates_bdf_when_identity_and_pci_in_separate_blocks(self) -> None:
        # vulkaninfo can repeat the GPUn: header — identity in one block, PCI info in
        # another. The index->BDF map must still associate them.
        output = (
            "GPU0:\n\tdeviceName = AMD Radeon Graphics (RADV GFX1201)\n\tvendorID = 0x1002\n"
            "GPU1:\n\tdeviceName = AMD Radeon Graphics (RADV GFX1201)\n\tvendorID = 0x1002\n"
            "GPU0:\n\tpciDomain = 0\n\tpciBus = 28\n\tpciDevice = 0\n\tpciFunction = 0\n"
            "GPU1:\n\tpciDomain = 0\n\tpciBus = 105\n\tpciDevice = 0\n\tpciFunction = 0\n"
        )
        self.assertEqual(
            parse_vulkaninfo_bdf_by_index(output),
            {0: "0000:1c:00.0", 1: "0000:69:00.0"},
        )

    def test_normalize_consistency_with_sysfs(self) -> None:
        # The BDF parsed from vulkaninfo decimal fields must equal the normalized
        # sysfs PCI_SLOT_NAME so the BDF->card lookup matches.
        block = "\tpciDomain = 0\n\tpciBus = 108\n\tpciDevice = 0\n\tpciFunction = 0\n"
        self.assertEqual(parse_vulkan_pci_bdf(block), normalize_pci_bdf("0000:6c:00.0"))


if __name__ == "__main__":
    unittest.main()
