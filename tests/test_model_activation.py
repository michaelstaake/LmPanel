import unittest
from unittest import mock

from app.core.model_activation import InsufficientHostRamError, assert_host_ram_for_activation


class AssertHostRamForActivationTests(unittest.TestCase):
    def test_passes_when_available_ram_exceeds_requirements(self) -> None:
        memory = mock.Mock(available=10 * 1024 * 1024 * 1024)
        with mock.patch("app.core.model_activation.psutil.virtual_memory", return_value=memory):
            assert_host_ram_for_activation(model_size_mb=1000, min_free_mb=4096, headroom_ratio=1.25)

    def test_requires_minimum_free_ram_when_model_size_unknown(self) -> None:
        memory = mock.Mock(available=2 * 1024 * 1024 * 1024)
        with mock.patch("app.core.model_activation.psutil.virtual_memory", return_value=memory):
            with self.assertRaises(InsufficientHostRamError):
                assert_host_ram_for_activation(model_size_mb=0, min_free_mb=4096, headroom_ratio=1.25)

    def test_requires_headroom_based_on_model_size(self) -> None:
        memory = mock.Mock(available=30 * 1024 * 1024 * 1024)
        with mock.patch("app.core.model_activation.psutil.virtual_memory", return_value=memory):
            with self.assertRaises(InsufficientHostRamError):
                assert_host_ram_for_activation(model_size_mb=28000, min_free_mb=4096, headroom_ratio=1.25)


if __name__ == "__main__":
    unittest.main()
