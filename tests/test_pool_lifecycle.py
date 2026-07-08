import unittest
from unittest import mock

from app.core.gpu_pool_manager import (
    degrade_pools_with_unavailable_devices,
    suspend_pool_models,
)
from app.core.inference_manager import InferenceManager, PoolActivationTarget, RunningModel
from app.core.pool_lifecycle import DeactivateReason
from app.inference_service import InferenceRuntime
from app.models.device import Device
from app.models.gpu_pool import GpuPool, GpuPoolDevice
from app.models.model_config import ModelConfig

SAMPLE_VULKANINFO = """
GPU0:
\tdeviceName = Card At 65
\tpciBusInfo = 0000:65:00.0
GPU1:
\tdeviceName = Card At 03
\tpciBusInfo = 0000:03:00.0
"""


class PoolLockingTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_pool_activation_rejected_while_first_active(self) -> None:
        manager = InferenceManager()
        manager._running[99] = RunningModel(
            model_id=99,
            base_url="http://runtime",
            device_id=None,
            vendor="vulkan_pool",
            pool_id=1,
            stable_hardware_ids=["0000:03:00.0", "0000:65:00.0"],
        )
        devices = [
            Device(id=1, hardware_id="vulkan:0", stable_hardware_id="0000:03:00.0", vendor="vulkan", name="GPU0", memory_mb=32000),
            Device(id=2, hardware_id="vulkan:1", stable_hardware_id="0000:65:00.0", vendor="vulkan", name="GPU1", memory_mb=32000),
        ]
        target = PoolActivationTarget(pool_id=1, pool_name="pool", vendor="vulkan", devices=devices)
        model = ModelConfig(
            id=2,
            file_name="test.gguf",
            model_dir_name="test",
            file_path="/models/test/test.gguf",
            alias="test2",
        )

        with mock.patch.object(InferenceManager, "runtime_url_for_vendor", return_value="http://runtime"):
            with self.assertRaisesRegex(RuntimeError, "already has an active model"):
                await manager.activate_model_on_pool(model, target)


class NonDestructivePoolRecoveryTests(unittest.TestCase):
    def test_suspend_pool_models_preserves_assignment(self) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.core.db import Base

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()

        pool = GpuPool(name="pool", vendor="vulkan", split_mode="layer")
        device_a = Device(hardware_id="vulkan:0", vendor="vulkan", name="GPU0", memory_mb=32000)
        device_b = Device(hardware_id="vulkan:1", vendor="vulkan", name="GPU1", memory_mb=32000)
        session.add_all([pool, device_a, device_b])
        session.flush()
        session.add_all(
            [
                GpuPoolDevice(pool_id=pool.id, device_id=device_a.id),
                GpuPoolDevice(pool_id=pool.id, device_id=device_b.id),
            ]
        )
        model = ModelConfig(
            file_name="test.gguf",
            model_dir_name="test",
            file_path="/models/test/test.gguf",
            alias="test",
            assignment_mode="pool",
            pinned_pool_id=pool.id,
            activated=True,
        )
        session.add(model)
        session.commit()

        manager = mock.Mock(spec=InferenceManager)
        suspended = suspend_pool_models(session, pool.id, manager)
        session.commit()
        session.refresh(model)

        self.assertEqual(len(suspended), 1)
        self.assertEqual(model.assignment_mode, "pool")
        self.assertEqual(model.pinned_pool_id, pool.id)
        self.assertTrue(model.activated)
        manager.deactivate_model_sync.assert_called_once()

    def test_degrade_pools_with_unavailable_devices_preserves_pool_row(self) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.core.db import Base

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()

        pool = GpuPool(name="pool", vendor="vulkan", split_mode="layer")
        device_a = Device(hardware_id="vulkan:0", vendor="vulkan", name="GPU0", memory_mb=32000, available=True)
        device_b = Device(hardware_id="vulkan:1", vendor="vulkan", name="GPU1", memory_mb=32000, available=False)
        session.add_all([pool, device_a, device_b])
        session.flush()
        session.add_all(
            [
                GpuPoolDevice(pool_id=pool.id, device_id=device_a.id),
                GpuPoolDevice(pool_id=pool.id, device_id=device_b.id),
            ]
        )
        model = ModelConfig(
            file_name="test.gguf",
            model_dir_name="test",
            file_path="/models/test/test.gguf",
            alias="test",
            assignment_mode="pool",
            pinned_pool_id=pool.id,
            activated=True,
        )
        session.add(model)
        session.commit()

        manager = mock.Mock(spec=InferenceManager)
        results = degrade_pools_with_unavailable_devices(session, {"vulkan:0"}, manager)
        session.commit()
        session.refresh(model)
        refreshed_pool = session.query(GpuPool).filter(GpuPool.id == pool.id).first()

        self.assertEqual(len(results), 1)
        self.assertIsNotNone(refreshed_pool)
        self.assertEqual(model.assignment_mode, "pool")
        self.assertEqual(model.pinned_pool_id, pool.id)


class VulkanPoolFailSafeTests(unittest.TestCase):
    def test_pool_launch_rejects_missing_bdf(self) -> None:
        runtime = InferenceRuntime()
        with mock.patch.object(InferenceRuntime, "_run_command", return_value=SAMPLE_VULKANINFO):
            with self.assertRaisesRegex(RuntimeError, "stable PCI BDF"):
                runtime._resolve_vulkan_indices(
                    ["vulkan:0", "vulkan:1"],
                    ["0000:03:00.0", ""],
                    pool_launch=True,
                )

    def test_pool_launch_rejects_duplicate_remap(self) -> None:
        runtime = InferenceRuntime()
        with mock.patch.object(InferenceRuntime, "_run_command", return_value=SAMPLE_VULKANINFO):
            with self.assertRaisesRegex(RuntimeError, "Duplicate Vulkan indices"):
                runtime._resolve_vulkan_indices(
                    ["vulkan:0", "vulkan:1"],
                    ["0000:03:00.0", "0000:03:00.0"],
                    pool_launch=True,
                )

    def test_pool_launch_rejects_unknown_bdf(self) -> None:
        runtime = InferenceRuntime()
        with mock.patch.object(InferenceRuntime, "_run_command", return_value=SAMPLE_VULKANINFO):
            with self.assertRaisesRegex(RuntimeError, "not present in the current Vulkan enumeration"):
                runtime._resolve_vulkan_indices(
                    ["vulkan:0", "vulkan:1"],
                    ["0000:99:00.0", "0000:03:00.0"],
                    pool_launch=True,
                )


class RuntimeStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_starting_state_while_activation_in_progress(self) -> None:
        manager = InferenceManager()
        manager._starting.add(1)
        state = await manager.resolve_runtime_state(1, activated=True)
        self.assertEqual(state["runtime_state"], "starting")

    async def test_backoff_limited_after_max_attempts(self) -> None:
        manager = InferenceManager()
        manager.record_recovery_failure(
            1,
            "failed",
            attempts=manager.settings.model_recovery_max_attempts,
            next_attempt=0.0,
            failure_kind="backoff_limited",
        )
        state = await manager.resolve_runtime_state(1, activated=True)
        self.assertEqual(state["runtime_state"], "backoff_limited")


class DeactivateReasonTests(unittest.TestCase):
    def test_sync_deactivate_logs_and_clears_running(self) -> None:
        manager = InferenceManager()
        manager._running[1] = RunningModel(
            model_id=1,
            base_url="http://runtime",
            device_id=1,
            vendor="vulkan",
            pool_id=5,
            stable_hardware_ids=["0000:03:00.0"],
        )
        with mock.patch.object(manager, "_deactivate_remote"):
            manager.deactivate_model_sync(1, reason=DeactivateReason.POOL_SUSPEND)
        self.assertNotIn(1, manager._running)


if __name__ == "__main__":
    unittest.main()
