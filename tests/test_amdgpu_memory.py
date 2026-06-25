import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.core.amdgpu_memory import (
    is_vulkan_integrated_gpu,
    read_amdgpu_device_metrics,
    read_amdgpu_gpu_usage,
    read_amdgpu_memory_metrics,
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

    def test_read_device_metrics_uses_fdinfo_when_sysfs_under_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            device_path = Path(tmpdir)
            (device_path / "mem_info_vram_total").write_text(str(24 * 1024**3))
            (device_path / "mem_info_vram_used").write_text(str(512 * 1024**2))

        with mock.patch(
            "app.core.amdgpu_memory.fdinfo_vram_mb_by_pid",
            return_value={1234: 12000},
        ):
            metrics = read_amdgpu_device_metrics(
                "0000:03:00.0",
                device_path,
                integrated=False,
                vulkan_used_mb=8000,
            )

        self.assertEqual(metrics["memory_used_mb"], 12000)
        self.assertEqual(metrics["memory_source"], "fdinfo")
        self.assertEqual(metrics["process_memory_by_pid"], {1234: 12000})
