import os
import unittest
from unittest import mock

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
        stale = Device(
            hardware_id="vulkan:0",
            name="Intel Arc A380",
            vendor="vulkan",
            device_type="gpu",
            memory_mb=6000,
            enabled=True,
        )
        current = Device(
            hardware_id="vulkan:1",
            name="AMD GPU",
            vendor="vulkan",
            device_type="gpu",
            memory_mb=32000,
            enabled=True,
        )
        db.add_all([stale, current])
        db.commit()

        removed = delete_unavailable_devices(db, {"vulkan:1"})
        db.commit()

        self.assertEqual(removed, [stale.id])
        remaining = {row.hardware_id for row in db.query(Device).all()}
        self.assertEqual(remaining, {"vulkan:1"})

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
                hardware_id="vulkan:1",
                stable_hardware_id=None,
                stable_hardware_id_source=None,
                name="NVIDIA GeForce RTX 4090",
                vendor="vulkan",
                device_type="gpu",
                memory_mb=32000,
            )
        ]

        with mock.patch.object(DeviceManager, "detect_all", return_value=detected):
            rows = manager.sync_detected_devices(db)

        hardware_ids = {row.hardware_id for row in rows}
        self.assertEqual(hardware_ids, {"vulkan:1"})
        self.assertEqual(db.query(Device).filter(Device.hardware_id == "vulkan:0").count(), 0)

    def test_default_name_for_device_uses_last_detected_map(self) -> None:
        db = _make_session()
        manager = DeviceManager()
        detected = [
            DetectedDevice(
                hardware_id="vulkan:0",
                stable_hardware_id=None,
                stable_hardware_id_source=None,
                name="NVIDIA GeForce RTX 4090",
                vendor="vulkan",
                device_type="gpu",
                memory_mb=32000,
            )
        ]

        with mock.patch.object(DeviceManager, "detect_all", return_value=detected):
            rows = manager.sync_detected_devices(db)

        device = rows[0]
        device.name = "Custom GPU Label"
        self.assertEqual(manager.default_name_for_device(device), "NVIDIA GeForce RTX 4090")

    def test_sync_preserves_device_when_vulkan_index_changes_but_stable_id_matches(self) -> None:
        db = _make_session()
        device = Device(
            hardware_id="vulkan:0",
            stable_hardware_id="0000:03:00.0",
            stable_hardware_id_source="pci_bdf",
            name="AMD Radeon RX 7900 XTX",
            vendor="vulkan",
            device_type="gpu",
            memory_mb=24576,
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
        device_id = device.id

        manager = DeviceManager()
        detected = [
            DetectedDevice(
                hardware_id="vulkan:1",
                stable_hardware_id="0000:03:00.0",
                stable_hardware_id_source="pci_bdf",
                name="AMD Radeon RX 7900 XTX",
                vendor="vulkan",
                device_type="gpu",
                memory_mb=24576,
            )
        ]

        with mock.patch.object(DeviceManager, "detect_all", return_value=detected):
            rows = manager.sync_detected_devices(db)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].id, device_id)
        self.assertEqual(rows[0].hardware_id, "vulkan:1")
        self.assertEqual(rows[0].stable_hardware_id, "0000:03:00.0")
        db.refresh(model)
        self.assertEqual(model.pinned_device_id, device_id)
        self.assertEqual(model.assignment_mode, "pinned")
        self.assertTrue(model.activated)


if __name__ == "__main__":
    unittest.main()
