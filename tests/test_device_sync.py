import os
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

for _env_key in (
    "STARTUP_HEALTHCHECK_INTERVAL",
    "STARTUP_HEALTHCHECK_TIMEOUT",
    "STARTUP_HEALTHCHECK_RETRIES",
    "STARTUP_HEALTHCHECK_START_PERIOD",
    "LLAMA_CPP_TAG",
):
    os.environ.pop(_env_key, None)

from app.core.db import Base
from app.core.device_manager import DetectedDevice, DeviceManager
from app.core.gpu_pool_manager import delete_unavailable_devices
from app.models.device import Device
from app.models.model_config import ModelConfig


def _make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


class DeleteUnavailableDevicesTests(unittest.TestCase):
    def test_removes_vulkan_device_when_not_detected(self) -> None:
        db = _make_session()
        vulkan = Device(
            hardware_id="vulkan:0",
            name="Intel Arc A380",
            vendor="vulkan",
            device_type="gpu",
            memory_mb=6000,
            enabled=True,
        )
        rocm = Device(
            hardware_id="rocm:0",
            name="Radeon AI PRO R9700",
            vendor="rocm",
            device_type="gpu",
            memory_mb=32000,
            enabled=True,
        )
        db.add_all([vulkan, rocm])
        db.commit()

        removed = delete_unavailable_devices(db, {"rocm:0"})
        db.commit()

        self.assertEqual(removed, [vulkan.id])
        remaining = {row.hardware_id for row in db.query(Device).all()}
        self.assertEqual(remaining, {"rocm:0"})

    def test_reverts_pinned_model_before_delete(self) -> None:
        db = _make_session()
        device = Device(
            hardware_id="vulkan:1",
            name="AMD GPU",
            vendor="vulkan",
            device_type="gpu",
            memory_mb=24000,
            enabled=True,
        )
        db.add(device)
        db.commit()

        model = ModelConfig(
            file_name="test.gguf",
            model_dir_name="test",
            file_path="/models/test.gguf",
            alias="test-model",
            assignment_mode="pinned",
            pinned_device_id=device.id,
            activated=True,
        )
        db.add(model)
        db.commit()

        delete_unavailable_devices(db, set())
        db.commit()

        db.refresh(model)
        self.assertIsNone(model.pinned_device_id)
        self.assertEqual(model.assignment_mode, "auto")
        self.assertFalse(model.activated)
        self.assertEqual(db.query(Device).count(), 0)


class SyncDetectedDevicesTests(unittest.TestCase):
    def test_sync_deletes_stale_vulkan_rows(self) -> None:
        db = _make_session()
        db.add(
            Device(
                hardware_id="vulkan:0",
                name="Stale Vulkan GPU",
                vendor="vulkan",
                device_type="gpu",
                memory_mb=8000,
                enabled=True,
            )
        )
        db.commit()

        manager = DeviceManager()
        detected = [
            DetectedDevice(
                hardware_id="rocm:0",
                stable_hardware_id="0000:03:00.0",
                stable_hardware_id_source="pci_bdf",
                name="Radeon AI PRO R9700",
                vendor="rocm",
                device_type="gpu",
                memory_mb=32000,
            )
        ]

        with unittest.mock.patch.object(DeviceManager, "detect_all", return_value=detected):
            rows = manager.sync_detected_devices(db)

        hardware_ids = {row.hardware_id for row in rows}
        self.assertEqual(hardware_ids, {"rocm:0"})
        self.assertEqual(db.query(Device).filter(Device.vendor == "vulkan").count(), 0)

    def test_default_name_for_device_uses_last_detected_map(self) -> None:
        db = _make_session()
        manager = DeviceManager()
        detected = [
            DetectedDevice(
                hardware_id="rocm:0",
                stable_hardware_id="0000:03:00.0",
                stable_hardware_id_source="pci_bdf",
                name="Radeon AI PRO R9700",
                vendor="rocm",
                device_type="gpu",
                memory_mb=32000,
            )
        ]

        with unittest.mock.patch.object(DeviceManager, "detect_all", return_value=detected):
            rows = manager.sync_detected_devices(db)

        device = rows[0]
        device.name = "Custom GPU Label"
        self.assertEqual(manager.default_name_for_device(device), "Radeon AI PRO R9700")


if __name__ == "__main__":
    unittest.main()
