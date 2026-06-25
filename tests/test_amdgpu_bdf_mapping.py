import unittest
from pathlib import Path
from unittest import mock

from app.core.device_manager import DeviceManager
from app.inference_service import InferenceRuntime


class AmdBdfMappingTests(unittest.TestCase):
    def test_device_manager_maps_amdgpu_memory_by_pci_bdf(self) -> None:
        manager = DeviceManager()
        cards = {
            "0000:03:00.0": Path("/sys/card-high"),
            "0000:0c:00.0": Path("/sys/card-low"),
        }

        def fake_read(device_path: Path, *, integrated: bool = False) -> dict:
            if device_path == Path("/sys/card-high"):
                return {"memory_total_mb": 24576}
            if device_path == Path("/sys/card-low"):
                return {"memory_total_mb": 8192}
            return {}

        with (
            mock.patch("app.core.device_manager.list_amdgpu_cards_by_bdf", return_value=cards),
            mock.patch("app.core.device_manager.read_amdgpu_memory_metrics", side_effect=fake_read),
        ):
            totals = manager._read_amdgpu_memory_totals(
                {0: "0000:0c:00.0", 1: "0000:03:00.0"},
                {0: False, 1: False},
            )

        self.assertEqual(totals[0], 8192)
        self.assertEqual(totals[1], 24576)

    def test_inference_runtime_maps_amdgpu_metrics_by_pci_bdf(self) -> None:
        runtime = InferenceRuntime()
        cards = {
            "0000:03:00.0": Path("/sys/card-high"),
            "0000:0c:00.0": Path("/sys/card-low"),
        }

        def fake_read(device_path: Path, *, integrated: bool = False) -> dict:
            if device_path == Path("/sys/card-high"):
                return {
                    "memory_total_mb": 24576,
                    "memory_used_mb": 1024,
                    "memory_source": "sysfs",
                }
            if device_path == Path("/sys/card-low"):
                return {
                    "memory_total_mb": 8192,
                    "memory_used_mb": 512,
                    "memory_source": "sysfs",
                }
            return {}

        vulkan_output = """
GPU0:
        deviceName         = AMD Radeon RX 580
        vendorID           = 0x1002
        deviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
        pciBusInfo         = 0000:0c:00.0
    memoryHeaps[0]:
        size = 8589934592 (8.00 GiB)
        usage = 0 (0.00 B)
        flags: count = 1
            MEMORY_HEAP_DEVICE_LOCAL_BIT
GPU1:
        deviceName         = AMD Radeon RX 7900 XTX
        vendorID           = 0x1002
        deviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
        pciBusInfo         = 0000:03:00.0
    memoryHeaps[0]:
        size = 25769803776 (24.00 GiB)
        usage = 0 (0.00 B)
        flags: count = 1
            MEMORY_HEAP_DEVICE_LOCAL_BIT
"""

        with (
            mock.patch.object(InferenceRuntime, "_run_command", return_value=vulkan_output),
            mock.patch("app.inference_service.list_amdgpu_cards_by_bdf", return_value=cards),
            mock.patch("app.inference_service.read_amdgpu_memory_metrics", side_effect=fake_read),
            mock.patch.object(InferenceRuntime, "_read_sysfs_percentage", return_value=10),
        ):
            metrics = runtime._collect_vulkan_metrics()

        self.assertEqual(metrics["vulkan:0"]["memory_total_mb"], 8192)
        self.assertEqual(metrics["vulkan:0"]["memory_used_mb"], 512)
        self.assertEqual(metrics["vulkan:1"]["memory_total_mb"], 24576)
        self.assertEqual(metrics["vulkan:1"]["memory_used_mb"], 1024)


if __name__ == "__main__":
    unittest.main()
