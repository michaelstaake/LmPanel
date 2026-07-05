import unittest

from app.core.inference_manager import PoolActivationTarget
from app.core.model_device_resolution import (
    best_fitting_pool_member,
    pick_best_pool_candidate,
    resolve_fitting_gpu,
)
from app.models.device import Device


def _device(device_id: int, hardware_id: str, *, available_mb: int = 0, priority: int = 0) -> Device:
    return Device(
        id=device_id,
        hardware_id=hardware_id,
        vendor="vulkan",
        name=f"GPU {device_id}",
        memory_mb=available_mb,
        priority=priority,
    )


class ResolveFittingGpuTests(unittest.TestCase):
    def test_prefers_gpu_with_most_available_vram(self) -> None:
        gpus = [_device(1, "vulkan:0", available_mb=20000), _device(2, "vulkan:1", available_mb=28000)]
        metrics = {
            "vulkan:0": {"total_mb": 32000, "available_mb": 20000},
            "vulkan:1": {"total_mb": 32000, "available_mb": 28000},
        }
        picked = resolve_fitting_gpu(gpus, 8000, metrics)
        self.assertEqual(picked.id, 2)

    def test_returns_none_when_no_gpu_fits(self) -> None:
        gpus = [_device(1, "vulkan:0", available_mb=4000)]
        metrics = {"vulkan:0": {"total_mb": 32000, "available_mb": 4000}}
        self.assertIsNone(resolve_fitting_gpu(gpus, 8000, metrics))


class BestFittingPoolMemberTests(unittest.TestCase):
    def test_returns_best_pool_member_when_model_fits(self) -> None:
        devices = [_device(1, "vulkan:0"), _device(2, "vulkan:1")]
        target = PoolActivationTarget(pool_id=1, pool_name="pool", vendor="vulkan", devices=devices)
        metrics = {
            "vulkan:0": {"total_mb": 32000, "available_mb": 25000},
            "vulkan:1": {"total_mb": 32000, "available_mb": 30000},
        }
        picked = best_fitting_pool_member(target, 8000, metrics)
        self.assertIsNotNone(picked)
        assert picked is not None
        self.assertEqual(picked.id, 2)

    def test_returns_none_when_model_needs_pool(self) -> None:
        devices = [_device(1, "vulkan:0"), _device(2, "vulkan:1")]
        target = PoolActivationTarget(pool_id=1, pool_name="pool", vendor="vulkan", devices=devices)
        metrics = {
            "vulkan:0": {"total_mb": 32000, "available_mb": 12000},
            "vulkan:1": {"total_mb": 32000, "available_mb": 12000},
        }
        self.assertIsNone(best_fitting_pool_member(target, 20000, metrics))


class PickBestPoolCandidateTests(unittest.TestCase):
    def test_sorts_by_priority_then_capacity(self) -> None:
        low_priority_devices = [_device(1, "vulkan:0", priority=5), _device(2, "vulkan:1", priority=5)]
        high_priority_devices = [_device(3, "vulkan:2", priority=1), _device(4, "vulkan:3", priority=1)]
        low = PoolActivationTarget(pool_id=1, pool_name="low", vendor="vulkan", devices=low_priority_devices)
        high = PoolActivationTarget(pool_id=2, pool_name="high", vendor="vulkan", devices=high_priority_devices)
        picked = pick_best_pool_candidate([(low, 50000), (high, 40000)])
        self.assertEqual(picked.pool_id, 2)


if __name__ == "__main__":
    unittest.main()
