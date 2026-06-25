import unittest
from pathlib import Path
from unittest import mock

from app.core.amdgpu_memory import apply_amdgpu_live_metrics, resolve_amdgpu_device_path
from app.core.device_manager import DeviceManager
from app.inference_service import InferenceRuntime


class AmdBdfMappingTests(unittest.TestCase):
    def test_device_manager_maps_amdgpu_memory_by_pci_bdf(self) -> None:
        manager = DeviceManager()
        cards = {
            "0000:03:00.0": Path("/sys/card-high"),
            "0000:0c:00.0": Path("/sys/card-low"),
        }
        ordered_paths = [Path("/sys/card-low"), Path("/sys/card-high")]

        def fake_resolve(
            pci_bdf: str | None,
            *,
            position: int | None = None,
            cards_by_bdf=None,
            ordered_paths=None,
        ) -> Path | None:
            if pci_bdf:
                normalized = pci_bdf.lower()
                if normalized in cards:
                    return cards[normalized]
            if position is not None and ordered_paths and position < len(ordered_paths):
                return ordered_paths[position]
            return None

        def fake_read(device_path: Path, *, integrated: bool = False) -> dict:
            if device_path == Path("/sys/card-high"):
                return {"memory_total_mb": 24576}
            if device_path == Path("/sys/card-low"):
                return {"memory_total_mb": 8192}
            return {}

        with (
            mock.patch("app.core.device_manager.resolve_amdgpu_device_path", side_effect=fake_resolve),
            mock.patch("app.core.device_manager.list_amdgpu_cards_by_bdf", return_value=cards),
            mock.patch("app.core.device_manager.list_amdgpu_device_paths", return_value=ordered_paths),
            mock.patch("app.core.device_manager.read_amdgpu_memory_metrics", side_effect=fake_read),
        ):
            totals = manager._read_amdgpu_memory_totals(
                [0, 1],
                {0: "0000:0c:00.0", 1: "0000:03:00.0"},
                {0: False, 1: False},
            )

        self.assertEqual(totals[0], 8192)
        self.assertEqual(totals[1], 24576)

    def test_resolve_falls_back_to_ordered_paths_when_bdf_missing(self) -> None:
        ordered_paths = [Path("/sys/card-low"), Path("/sys/card-high")]
        path = resolve_amdgpu_device_path(
            None,
            position=1,
            cards_by_bdf={},
            ordered_paths=ordered_paths,
        )
        self.assertEqual(path, Path("/sys/card-high"))

    def test_inference_runtime_maps_amdgpu_metrics_by_pci_bdf(self) -> None:
        runtime = InferenceRuntime()
        cards = {
            "0000:03:00.0": Path("/sys/card-high"),
            "0000:0c:00.0": Path("/sys/card-low"),
        }
        ordered_paths = [Path("/sys/card-low"), Path("/sys/card-high")]

        def fake_apply(metric: dict, device_path: Path, *, pci_bdf=None, integrated: bool = False) -> None:
            if device_path == Path("/sys/card-high"):
                metric.update(
                    {
                        "memory_total_mb": 24576,
                        "memory_used_mb": 1024,
                        "memory_source": "sysfs",
                        "usage_percent": 10,
                        "usage_source": "sysfs",
                    }
                )
            elif device_path == Path("/sys/card-low"):
                metric.update(
                    {
                        "memory_total_mb": 8192,
                        "memory_used_mb": 512,
                        "memory_source": "sysfs",
                        "usage_percent": 10,
                        "usage_source": "sysfs",
                    }
                )

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
            mock.patch("app.inference_service.list_amdgpu_device_paths", return_value=ordered_paths),
            mock.patch("app.inference_service.resolve_amdgpu_device_path", side_effect=lambda pci_bdf, **kwargs: cards.get((pci_bdf or "").lower()) or ordered_paths[kwargs.get("position", 0)]),
            mock.patch("app.inference_service.apply_amdgpu_live_metrics", side_effect=fake_apply),
        ):
            metrics = runtime._collect_vulkan_metrics()

        self.assertEqual(metrics["vulkan:0"]["memory_total_mb"], 8192)
        self.assertEqual(metrics["vulkan:0"]["memory_used_mb"], 512)
        self.assertEqual(metrics["vulkan:0"]["usage_percent"], 10)
        self.assertEqual(metrics["vulkan:1"]["memory_total_mb"], 24576)
        self.assertEqual(metrics["vulkan:1"]["memory_used_mb"], 1024)


if __name__ == "__main__":
    unittest.main()
