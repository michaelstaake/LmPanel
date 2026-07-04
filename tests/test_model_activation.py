import unittest
from unittest import mock

from app.core.model_activation import (
    InsufficientHostRamError,
    assert_host_ram_for_activation,
    resolve_activation_headroom_ratio,
)


def _assert_ram(**kwargs) -> None:
    defaults = {
        "model_size_mb": 1000,
        "min_free_mb": 4096,
        "gpu_layers": 99,
        "memory_mapping_enabled": True,
        "cpu_headroom_ratio": 1.25,
        "gpu_mmap_headroom_ratio": 0.20,
        "gpu_no_mmap_headroom_ratio": 0.50,
    }
    defaults.update(kwargs)
    assert_host_ram_for_activation(**defaults)


class ResolveActivationHeadroomRatioTests(unittest.TestCase):
    def test_cpu_inference_uses_cpu_ratio(self) -> None:
        ratio = resolve_activation_headroom_ratio(
            gpu_layers=0,
            memory_mapping_enabled=True,
            cpu_headroom_ratio=1.25,
            gpu_mmap_headroom_ratio=0.20,
            gpu_no_mmap_headroom_ratio=0.50,
        )
        self.assertEqual(ratio, 1.25)

    def test_gpu_mmap_uses_gpu_mmap_ratio(self) -> None:
        ratio = resolve_activation_headroom_ratio(
            gpu_layers=99,
            memory_mapping_enabled=True,
            cpu_headroom_ratio=1.25,
            gpu_mmap_headroom_ratio=0.20,
            gpu_no_mmap_headroom_ratio=0.50,
        )
        self.assertEqual(ratio, 0.20)

    def test_gpu_no_mmap_uses_intermediate_ratio(self) -> None:
        ratio = resolve_activation_headroom_ratio(
            gpu_layers=99,
            memory_mapping_enabled=False,
            cpu_headroom_ratio=1.25,
            gpu_mmap_headroom_ratio=0.20,
            gpu_no_mmap_headroom_ratio=0.50,
        )
        self.assertEqual(ratio, 0.50)


class AssertHostRamForActivationTests(unittest.TestCase):
    def test_passes_when_available_ram_exceeds_requirements(self) -> None:
        memory = mock.Mock(available=10 * 1024 * 1024 * 1024)
        with mock.patch("app.core.model_activation.psutil.virtual_memory", return_value=memory):
            _assert_ram(model_size_mb=1000)

    def test_requires_minimum_free_ram_when_model_size_unknown(self) -> None:
        memory = mock.Mock(available=2 * 1024 * 1024 * 1024)
        with mock.patch("app.core.model_activation.psutil.virtual_memory", return_value=memory):
            with self.assertRaises(InsufficientHostRamError):
                _assert_ram(model_size_mb=0)

    def test_requires_headroom_based_on_model_size_for_cpu(self) -> None:
        memory = mock.Mock(available=30 * 1024 * 1024 * 1024)
        with mock.patch("app.core.model_activation.psutil.virtual_memory", return_value=memory):
            with self.assertRaises(InsufficientHostRamError):
                _assert_ram(model_size_mb=28000, gpu_layers=0)

    def test_allows_large_gpu_mmap_model_with_modest_host_ram(self) -> None:
        memory = mock.Mock(available=16 * 1024 * 1024 * 1024)
        with mock.patch("app.core.model_activation.psutil.virtual_memory", return_value=memory):
            _assert_ram(model_size_mb=60000, gpu_layers=99, memory_mapping_enabled=True)

    def test_requires_more_host_ram_for_gpu_without_mmap(self) -> None:
        memory = mock.Mock(available=16 * 1024 * 1024 * 1024)
        with mock.patch("app.core.model_activation.psutil.virtual_memory", return_value=memory):
            with self.assertRaises(InsufficientHostRamError):
                _assert_ram(model_size_mb=60000, gpu_layers=99, memory_mapping_enabled=False)


if __name__ == "__main__":
    unittest.main()
