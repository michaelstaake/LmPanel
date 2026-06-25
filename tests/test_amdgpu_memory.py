import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.core.amdgpu_memory import (
    apply_amdgpu_live_metrics,
    is_vulkan_integrated_gpu,
    read_amdgpu_gpu_usage,
    read_amdgpu_memory_metrics,
    resolve_amdgpu_device_path,
    should_include_gtt,
)


class AmdgpuMemoryTests(unittest.TestCase):
    def test_is_vulkan_integrated_gpu(self) -> None:
        self.assertTrue(is_vulkan_integrated_gpu("physical_device_type_integrated_gpu"))
        self.assertFalse(is_vulkan_integrated_gpu("physical_device_type_discrete_gpu"))

    def test_should_include_gtt_integrated(self) -> None:
        self.assertTrue(
            should_include_gtt(512 * 1024**2, 8 * 1024**3, integrated=True),
        )

    def test_should_include_gtt_apu_heuristic(self) -> None:
        self.assertTrue(
            should_include_gtt(512 * 1024**2, 8 * 1024**3, integrated=False),
        )

    def test_should_not_include_gtt_discrete(self) -> None:
        self.assertFalse(
            should_include_gtt(24 * 1024**3, 32 * 1024**3, integrated=False),
        )

    def test_read_integrated_apu_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            device_path = Path(tmpdir)
            (device_path / "mem_info_vram_total").write_text(str(512 * 1024**2))
            (device_path / "mem_info_vram_used").write_text(str(92 * 1024**2))
            (device_path / "mem_info_gtt_total").write_text(str(8192 * 1024**2))
            (device_path / "mem_info_gtt_used").write_text(str(633 * 1024**2))

            metrics = read_amdgpu_memory_metrics(device_path, integrated=True)

        self.assertEqual(metrics["memory_total_mb"], 8704)
        self.assertEqual(metrics["memory_used_mb"], 725)
        self.assertEqual(metrics["memory_source"], "sysfs-gtt")

    def test_read_discrete_metrics_vram_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            device_path = Path(tmpdir)
            (device_path / "mem_info_vram_total").write_text(str(24 * 1024**3))
            (device_path / "mem_info_vram_used").write_text(str(4 * 1024**3))
            (device_path / "mem_info_gtt_total").write_text(str(32 * 1024**3))
            (device_path / "mem_info_gtt_used").write_text(str(1 * 1024**3))

            metrics = read_amdgpu_memory_metrics(device_path, integrated=False)

        self.assertEqual(metrics["memory_total_mb"], 24576)
        self.assertEqual(metrics["memory_used_mb"], 4096)
        self.assertEqual(metrics["memory_source"], "sysfs")

    def test_read_gpu_usage_prefers_gpu_busy_percent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            device_path = Path(tmpdir)
            (device_path / "gpu_busy_percent").write_text("42")
            (device_path / "mem_busy_percent").write_text("99")

            self.assertEqual(read_amdgpu_gpu_usage(device_path), 42)

    def test_apply_live_metrics_uses_fdinfo_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            device_path = Path(tmpdir)
            (device_path / "mem_info_vram_total").write_text(str(24 * 1024**3))
            (device_path / "mem_info_vram_used").write_text(str(512 * 1024**2))
            (device_path / "gpu_busy_percent").write_text("55")

        metric = {"memory_used_mb": 100, "memory_source": "vulkaninfo"}
        with (
            mock.patch("app.core.amdgpu_memory.fdinfo_vram_mb_by_pid", return_value={1234: 12000}),
            mock.patch("app.core.amdgpu_memory.read_amdgpu_gpu_usage", return_value=55),
        ):
            apply_amdgpu_live_metrics(metric, device_path, pci_bdf="0000:03:00.0", integrated=False)

        self.assertEqual(metric["memory_used_mb"], 12000)
        self.assertEqual(metric["usage_percent"], 55)
        self.assertEqual(metric["process_memory_by_pid"], {1234: 12000})

    def test_resolve_prefers_bdf_path_with_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            good = root / "good"
            bad = root / "bad"
            good.mkdir()
            bad.mkdir()
            (good / "gpu_busy_percent").write_text("12")
            (good / "mem_info_vram_total").write_text(str(8 * 1024**3))

            cards = {"0000:03:00.0": bad, "0000:0c:00.0": good}
            ordered = [good]

            path = resolve_amdgpu_device_path(
                "0000:03:00.0",
                position=0,
                cards_by_bdf=cards,
                ordered_paths=ordered,
            )
            self.assertEqual(path, good)


if __name__ == "__main__":
    unittest.main()
