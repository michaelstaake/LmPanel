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
from app.core.device_manager import DetectedDevice, DetectionResult, DeviceManager
from app.core.gpu_pool_manager import delete_unavailable_devices, mark_unavailable_devices
from app.models.device import Device
from app.models.gpu_pool import GpuPool, GpuPoolDevice
from app.models.model_config import ModelConfig


def _detection(devices, authoritative=True):
    return DetectionResult(devices=list(devices), authoritative=authoritative)


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
    def test_sync_persists_pci_vendor_id(self) -> None:
        db = _make_session()
        manager = DeviceManager()
        detected = [
            DetectedDevice(
                hardware_id="vulkan:0",
                stable_hardware_id="0000:01:00.0",
                stable_hardware_id_source="pci_bdf",
                name="AMD Radeon RX 9070",
                vendor="vulkan",
                device_type="gpu",
                memory_mb=16000,
                pci_vendor_id=0x1002,
            ),
            DetectedDevice(
                hardware_id="vulkan:1",
                stable_hardware_id="0000:02:00.0",
                stable_hardware_id_source="pci_bdf",
                name="NVIDIA GeForce RTX 5060 Ti",
                vendor="vulkan",
                device_type="gpu",
                memory_mb=16000,
                pci_vendor_id=0x10DE,
            ),
        ]

        with mock.patch.object(DeviceManager, "detect_all_with_status", return_value=_detection(detected)):
            manager.sync_detected_devices(db)

        rows = {row.hardware_id: row for row in db.query(Device).all()}
        self.assertEqual(rows["vulkan:0"].pci_vendor_id, 0x1002)
        self.assertEqual(rows["vulkan:1"].pci_vendor_id, 0x10DE)

    def test_sync_soft_disables_undetected_vulkan_rows(self) -> None:
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

        with mock.patch.object(DeviceManager, "detect_all_with_status", return_value=_detection(detected)):
            rows = manager.sync_detected_devices(db)

        # The undetected device is NOT deleted — it is soft-disabled and preserved.
        hardware_ids = {row.hardware_id for row in rows}
        self.assertEqual(hardware_ids, {"vulkan:0", "vulkan:1"})
        stale = db.query(Device).filter(Device.hardware_id == "vulkan:0").one()
        self.assertFalse(stale.available)
        current = db.query(Device).filter(Device.hardware_id == "vulkan:1").one()
        self.assertTrue(current.available)

    def test_sync_skips_reconciliation_when_not_authoritative(self) -> None:
        db = _make_session()
        db.add(
            Device(
                hardware_id="vulkan:0",
                stable_hardware_id="0000:03:00.0",
                name="AMD GPU",
                vendor="vulkan",
                device_type="gpu",
                memory_mb=24000,
                enabled=True,
            )
        )
        db.commit()

        manager = DeviceManager()
        # Runtime unreachable -> empty + non-authoritative. Must NOT touch existing rows.
        with mock.patch.object(
            DeviceManager, "detect_all_with_status", return_value=_detection([], authoritative=False)
        ):
            rows = manager.sync_detected_devices(db)

        self.assertEqual(len(rows), 1)
        device = db.query(Device).filter(Device.hardware_id == "vulkan:0").one()
        self.assertTrue(device.available)

    def test_sync_skips_reconciliation_when_no_gpu_detected_but_gpu_in_db(self) -> None:
        db = _make_session()
        db.add(
            Device(
                hardware_id="vulkan:0",
                stable_hardware_id="0000:03:00.0",
                name="AMD GPU",
                vendor="vulkan",
                device_type="gpu",
                memory_mb=24000,
                enabled=True,
            )
        )
        db.commit()

        manager = DeviceManager()
        # Authoritative, but only CPU detected while a GPU exists in DB -> likely a
        # timing/probe failure; preserve the GPU rather than soft-disabling it.
        cpu_only = [
            DetectedDevice(
                hardware_id="cpu:0",
                stable_hardware_id=None,
                stable_hardware_id_source=None,
                name="CPU",
                vendor="cpu",
                device_type="cpu",
                memory_mb=64000,
            )
        ]
        with mock.patch.object(DeviceManager, "detect_all_with_status", return_value=_detection(cpu_only)):
            manager.sync_detected_devices(db)

        device = db.query(Device).filter(Device.hardware_id == "vulkan:0").one()
        self.assertTrue(device.available)

    def test_sync_reenables_returning_device(self) -> None:
        db = _make_session()
        device = Device(
            hardware_id="vulkan:0",
            stable_hardware_id="0000:03:00.0",
            name="AMD GPU",
            vendor="vulkan",
            device_type="gpu",
            memory_mb=24000,
            enabled=True,
            available=False,
        )
        db.add(device)
        db.commit()

        manager = DeviceManager()
        detected = [
            DetectedDevice(
                hardware_id="vulkan:0",
                stable_hardware_id="0000:03:00.0",
                stable_hardware_id_source="pci_bdf",
                name="AMD GPU",
                vendor="vulkan",
                device_type="gpu",
                memory_mb=24000,
            )
        ]
        with mock.patch.object(DeviceManager, "detect_all_with_status", return_value=_detection(detected)):
            manager.sync_detected_devices(db)

        db.refresh(device)
        self.assertTrue(device.available)
        self.assertIsNotNone(device.last_seen_at)

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

        with mock.patch.object(DeviceManager, "detect_all_with_status", return_value=_detection(detected)):
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

        with mock.patch.object(DeviceManager, "detect_all_with_status", return_value=_detection(detected)):
            rows = manager.sync_detected_devices(db)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].id, device_id)
        self.assertEqual(rows[0].hardware_id, "vulkan:1")
        self.assertEqual(rows[0].stable_hardware_id, "0000:03:00.0")
        db.refresh(model)
        self.assertEqual(model.pinned_device_id, device_id)
        self.assertEqual(model.assignment_mode, "pinned")
        self.assertTrue(model.activated)


class MarkUnavailableDevicesTests(unittest.TestCase):
    def test_soft_disable_preserves_pool_membership_and_pin(self) -> None:
        db = _make_session()
        gpu_a = Device(hardware_id="vulkan:0", stable_hardware_id="0000:03:00.0", name="A", vendor="vulkan", device_type="gpu", memory_mb=24000, enabled=True)
        gpu_b = Device(hardware_id="vulkan:1", stable_hardware_id="0000:65:00.0", name="B", vendor="vulkan", device_type="gpu", memory_mb=24000, enabled=True)
        db.add_all([gpu_a, gpu_b])
        db.commit()

        pool = GpuPool(name="Pool", vendor="vulkan", split_mode="layer")
        db.add(pool)
        db.commit()
        db.add_all([
            GpuPoolDevice(pool_id=pool.id, device_id=gpu_a.id),
            GpuPoolDevice(pool_id=pool.id, device_id=gpu_b.id),
        ])
        model = ModelConfig(
            file_name="m.gguf", model_dir_name="m", file_path="/models/m.gguf", alias="m",
            assignment_mode="pool", pinned_pool_id=pool.id, activated=True,
        )
        db.add(model)
        db.commit()

        # Only gpu_a detected; gpu_b transiently missing.
        changed = mark_unavailable_devices(db, {"vulkan:0"}, detected_stable_hardware_ids={"0000:03:00.0"})
        db.commit()

        self.assertEqual(changed, [gpu_b.id])
        # Membership and pin are fully preserved for automatic recovery.
        self.assertEqual(db.query(GpuPoolDevice).filter(GpuPoolDevice.pool_id == pool.id).count(), 2)
        db.refresh(model)
        self.assertEqual(model.pinned_pool_id, pool.id)
        self.assertTrue(model.activated)
        db.refresh(gpu_b)
        self.assertFalse(gpu_b.available)


if __name__ == "__main__":
    unittest.main()
