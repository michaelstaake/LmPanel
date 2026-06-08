from pathlib import Path
from unittest.mock import patch

from app.core.device_manager import DeviceManager


def test_detect_anpu_when_accel_device_present() -> None:
    manager = DeviceManager()

    def fake_exists(self: Path) -> bool:
        return str(self) == "/dev/accel/accel0"

    with patch("app.core.device_manager.is_supported_vendor", return_value=True):
        with patch.object(Path, "exists", fake_exists):
            devices = manager._detect_anpu()

    assert len(devices) == 1
    assert devices[0].vendor == "anpu"
    assert devices[0].hardware_id == "anpu:0"
    assert devices[0].device_type == "npu"
    assert devices[0].max_slots == 1


def test_detect_anpu_returns_empty_without_device() -> None:
    manager = DeviceManager()
    with patch("app.core.device_manager.is_supported_vendor", return_value=True):
        with patch.object(Path, "exists", return_value=False):
            assert manager._detect_anpu() == []
