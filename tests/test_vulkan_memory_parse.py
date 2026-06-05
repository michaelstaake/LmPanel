import unittest

from app.core.device_manager import (
    _parse_vulkaninfo_device_local_heap_mb,
    _parse_vulkaninfo_gpu_memory_metrics,
)

MODERN_INTEL_ARC_A380 = """
GPU0:
        deviceName         = Intel(R) Arc(TM) A380 Graphics
        vendorID           = 0x8086
        deviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
    memoryHeaps[0]:
        size = 6081740800 (0x16b400000) (5.66 GiB)
        budget = 5800000000 (0x159f99900) (5.40 GiB)
        usage = 1073741824 (0x40000000) (1.00 GiB)
        flags: count = 1
            MEMORY_HEAP_DEVICE_LOCAL_BIT
    memoryHeaps[1]:
        size = 17094656000 (0x3f9e40000) (15.93 GiB)
        budget = 16000000000 (0x3b9aca000) (14.90 GiB)
        usage = 0 (0x00000000) (0.00 B)
        flags:
            None
    memoryHeaps[2]:
        size = 268435456 (0x10000000) (256.00 MiB)
        budget = 200000000 (0x0bebc200) (190.73 MiB)
        usage = 0 (0x00000000) (0.00 B)
        flags: count = 1
            MEMORY_HEAP_DEVICE_LOCAL_BIT
"""

INTEL_ARC_LOADED = """
GPU0:
        deviceName         = Intel(R) Arc(TM) A380 Graphics
        vendorID           = 0x8086
        deviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
    memoryHeaps[0]:
        size = 6081740800 (0x16b400000) (5.66 GiB)
        budget = 5800000000 (0x159f99900) (5.40 GiB)
        usage = 1073741824 (0x40000000) (1.00 GiB)
        flags: count = 1
            MEMORY_HEAP_DEVICE_LOCAL_BIT
    memoryHeaps[1]:
        size = 17094656000 (0x3f9e40000) (15.93 GiB)
        budget = 16000000000 (0x3b9aca000) (14.90 GiB)
        usage = 3221225472 (0xc0000000) (3.00 GiB)
        flags:
            None
    memoryHeaps[2]:
        size = 268435456 (0x10000000) (256.00 MiB)
        budget = 200000000 (0x0bebc200) (190.73 MiB)
        usage = 0 (0x00000000) (0.00 B)
        flags: count = 1
            MEMORY_HEAP_DEVICE_LOCAL_BIT
"""

LEGACY_VK_PREFIX = """
GPU1:
        deviceName         = Example GPU
        vendorID           = 0x8086
    memoryHeaps[0]:
        size = 8192 MiB
        usage = 512 MiB
        flags: count = 1
            VK_MEMORY_HEAP_DEVICE_LOCAL_BIT
"""

NO_DEVICE_LOCAL = """
GPU2:
        deviceName         = Software Renderer
    memoryHeaps[0]:
        size = 16384 MiB
        flags:
            None
"""


class VulkanMemoryParseTests(unittest.TestCase):
    def test_modern_anv_arc_a380_layout(self) -> None:
        metrics = _parse_vulkaninfo_gpu_memory_metrics(MODERN_INTEL_ARC_A380)
        self.assertIn(0, metrics)
        self.assertGreaterEqual(metrics[0]["total_mb"], 5700)
        self.assertLessEqual(metrics[0]["total_mb"], 5900)
        self.assertEqual(metrics[0]["used_mb"], 1024)

    def test_modern_heap_totals_exclude_system_ram(self) -> None:
        totals = _parse_vulkaninfo_device_local_heap_mb(MODERN_INTEL_ARC_A380)
        self.assertEqual(totals[0], _parse_vulkaninfo_gpu_memory_metrics(MODERN_INTEL_ARC_A380)[0]["total_mb"])
        self.assertLess(totals[0], 10000)

    def test_intel_arc_sums_all_heap_usage(self) -> None:
        metrics = _parse_vulkaninfo_gpu_memory_metrics(INTEL_ARC_LOADED)
        self.assertEqual(metrics[0]["used_mb"], 4096)
        self.assertGreaterEqual(metrics[0]["total_mb"], 5700)
        self.assertLessEqual(metrics[0]["total_mb"], 5900)

    def test_legacy_vk_memory_heap_flag(self) -> None:
        metrics = _parse_vulkaninfo_gpu_memory_metrics(LEGACY_VK_PREFIX)
        self.assertEqual(metrics[1]["total_mb"], 8192)
        self.assertEqual(metrics[1]["used_mb"], 512)

    def test_no_device_local_heaps(self) -> None:
        metrics = _parse_vulkaninfo_gpu_memory_metrics(NO_DEVICE_LOCAL)
        self.assertEqual(metrics, {})


if __name__ == "__main__":
    unittest.main()
