import unittest
from unittest import mock

from app.core.config import Settings
from app.core.llama_failure import classify_llama_log, log_indicates_tensor_split_unsupported
from app.core.model_activation import InsufficientGttError, InsufficientVramError, assert_gtt_headroom_for_activation
from app.core.pool_lifecycle import FailureKind
from app.core.vram_estimator import estimate_activation_vram_mb, pool_member_vram_share
from app.core.vram_preflight import assert_pool_members_vram_available, estimate_model_vram_need_mb
from app.core.inference_manager import InferenceManager, PoolActivationTarget
from app.inference_service import ActivateModelRequest, InferenceRuntime
from app.models.device import Device
from app.models.model_config import ModelConfig


class VramEstimatorTests(unittest.TestCase):
    def test_single_gpu_estimate_includes_kv_and_margins(self) -> None:
        need = estimate_activation_vram_mb(
            model_size_mb=20000,
            context_length=32768,
            gpu_layers=99,
            kv_mb_per_1k_tokens=80.0,
            compute_margin_mb=512,
            headroom_mb=1024,
        )
        kv = int((32768 / 1000) * 80 * 0.5)  # default q8-scale when cache types unset
        self.assertEqual(need, 20000 + kv + 512 + 1024)

    def test_pool_share_halves_estimate(self) -> None:
        self.assertEqual(pool_member_vram_share(32000, 64000), 0.5)


class LlamaFailureClassificationTests(unittest.TestCase):
    def test_device_lost_from_vulkan_log(self) -> None:
        log = "ggml_vulkan: vkQueueSubmit failed VK_ERROR_DEVICE_LOST"
        self.assertEqual(classify_llama_log(log), FailureKind.DEVICE_LOST)

    def test_generic_for_benign_log(self) -> None:
        self.assertEqual(classify_llama_log("loaded model ok"), FailureKind.GENERIC)

    def test_tensor_unsupported_pattern(self) -> None:
        self.assertTrue(log_indicates_tensor_split_unsupported("tensor split not supported on this backend"))


class GttHeadroomTests(unittest.TestCase):
    def test_rejects_high_gtt_usage(self) -> None:
        metrics = {
            "vulkan:0": {
                "stable_hardware_id": "0000:03:00.0",
                "gtt_total_mb": 10000,
                "gtt_used_mb": 9000,
            }
        }
        with self.assertRaises(InsufficientGttError):
            assert_gtt_headroom_for_activation(
                stable_hardware_ids=["0000:03:00.0"],
                memory_metrics=metrics,
                max_used_ratio=0.85,
            )


class FlashAttentionFlagTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = InferenceRuntime()
        mock.patch.object(
            InferenceRuntime,
            "_resolve_llama_server_path",
            return_value="/opt/llama.cpp/build/bin/llama-server",
        ).start()
        self.addCleanup(mock.patch.stopall)

    def _payload(self, **overrides) -> ActivateModelRequest:
        defaults = {
            "model_id": 1,
            "alias": "test",
            "file_path": "/models/test.gguf",
            "context_length": 8192,
            "threads": 8,
            "gpu_layers": 99,
            "vendor": "vulkan",
            "hardware_id": "vulkan:0",
            "flash_attention_enabled": False,
        }
        defaults.update(overrides)
        return ActivateModelRequest(**defaults)

    def test_vulkan_auto_default_uses_auto_when_model_disabled(self) -> None:
        command = self.runtime._build_llama_command(self._payload(), 8101, 99)
        idx = command.index("--flash-attn")
        self.assertEqual(command[idx + 1], "auto")

    def test_tensor_pool_still_forces_on(self) -> None:
        command = self.runtime._build_llama_command(
            self._payload(vendor="vulkan_pool", split_mode="tensor", vram_ratios=[32000, 32000]),
            8101,
            99,
        )
        idx = command.index("--flash-attn")
        self.assertEqual(command[idx + 1], "on")

    def test_vulkan_force_off_via_setting(self) -> None:
        runtime = InferenceRuntime()
        runtime.settings = Settings(vulkan_flash_attention_default="off")
        command = runtime._build_llama_command(self._payload(), 8101, 99)
        idx = command.index("--flash-attn")
        self.assertEqual(command[idx + 1], "off")


class StallTimeoutTests(unittest.TestCase):
    def test_stream_read_timeout_shorter_than_request(self) -> None:
        runtime = InferenceRuntime()
        timeout = runtime._llama_http_timeout(for_stream=True)
        self.assertEqual(timeout.read, runtime.settings.llama_stream_stall_timeout_seconds)
        self.assertEqual(timeout.read, 120)


class PoolVramPreflightTests(unittest.TestCase):
    def test_rejects_member_short_on_vram(self) -> None:
        model = ModelConfig(
            id=1,
            file_name="m.gguf",
            model_dir_name="m",
            file_path="/models/m/m.gguf",
            alias="m",
            context_length=8192,
            gpu_layers=99,
        )
        devices = [
            Device(id=1, hardware_id="vulkan:0", vendor="vulkan", name="GPU0", memory_mb=32000),
            Device(id=2, hardware_id="vulkan:1", vendor="vulkan", name="GPU1", memory_mb=32000),
        ]
        target = PoolActivationTarget(pool_id=1, pool_name="p", vendor="vulkan", devices=devices)
        settings = Settings()
        with (
            mock.patch("app.core.vram_preflight.estimate_model_file_size_mb", return_value=60000),
            self.assertRaises(InsufficientVramError),
        ):
            assert_pool_members_vram_available(
                model=model,
                target=target,
                memory_metrics={
                    "vulkan:0": {"total_mb": 32000, "available_mb": 2000},
                    "vulkan:1": {"total_mb": 32000, "available_mb": 2000},
                },
                settings=settings,
            )


class DeviceCooldownTests(unittest.IsolatedAsyncioTestCase):
    def test_cooldown_blocks_until_healthy_ticks(self) -> None:
        manager = InferenceManager()
        manager.mark_devices_need_cooldown(["0000:03:00.0"])
        self.assertFalse(manager.device_cooldown_satisfied(["0000:03:00.0"]))
        metrics = {
            "vulkan:0": {
                "stable_hardware_id": "0000:03:00.0",
                "gtt_total_mb": 10000,
                "gtt_used_mb": 100,
            }
        }
        manager.tick_device_health(metrics)
        manager.tick_device_health(metrics)
        self.assertTrue(manager.device_cooldown_satisfied(["0000:03:00.0"]))


if __name__ == "__main__":
    unittest.main()
