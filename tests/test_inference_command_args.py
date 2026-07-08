import unittest
from unittest import mock

from pydantic import ValidationError

from app.core.inference_manager import InferenceManager, PoolActivationTarget
from app.inference_service import ActivateModelRequest, InferenceRuntime
from app.models.device import Device
from app.models.model_config import ModelConfig
from app.utils.schemas import ModelUpdateRequest


def _base_payload(**overrides) -> ActivateModelRequest:
    defaults = {
        "model_id": 1,
        "alias": "test-model",
        "file_path": "/models/test.gguf",
        "context_length": 8192,
        "threads": 8,
        "gpu_layers": 99,
        "vendor": "vulkan",
        "hardware_id": "vulkan:0",
    }
    defaults.update(overrides)
    return ActivateModelRequest(**defaults)


class BuildLlamaCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = InferenceRuntime()
        mock.patch.object(
            InferenceRuntime,
            "_resolve_llama_server_path",
            return_value="/opt/llama.cpp/build/bin/llama-server",
        ).start()
        self.addCleanup(mock.patch.stopall)

    def test_batch_flags_omitted_when_null(self) -> None:
        command = self.runtime._build_llama_command(_base_payload(), 8101, 99)
        self.assertNotIn("--batch-size", command)
        self.assertNotIn("--ubatch-size", command)

    def test_batch_flags_emitted_when_set(self) -> None:
        command = self.runtime._build_llama_command(
            _base_payload(batch_size=16384, ubatch_size=2048),
            8101,
            99,
        )
        batch_idx = command.index("--batch-size")
        self.assertEqual(command[batch_idx + 1], "16384")
        ubatch_idx = command.index("--ubatch-size")
        self.assertEqual(command[ubatch_idx + 1], "2048")

    def test_flash_attn_forced_on_for_vulkan_pool_tensor(self) -> None:
        command = self.runtime._build_llama_command(
            _base_payload(
                vendor="vulkan_pool",
                split_mode="tensor",
                flash_attention_enabled=False,
                vram_ratios=[32000, 32000],
            ),
            8101,
            99,
        )
        flash_idx = command.index("--flash-attn")
        self.assertEqual(command[flash_idx + 1], "on")

    def test_layer_mode_uses_auto_flash_attention_on_vulkan_pool(self) -> None:
        command = self.runtime._build_llama_command(
            _base_payload(
                vendor="vulkan_pool",
                split_mode="layer",
                flash_attention_enabled=False,
                vram_ratios=[32000, 32000],
            ),
            8101,
            99,
        )
        flash_idx = command.index("--flash-attn")
        self.assertEqual(command[flash_idx + 1], "auto")
        split_idx = command.index("--split-mode")
        self.assertEqual(command[split_idx + 1], "layer")

    def test_pool_defaults_batch_sizes_when_unset(self) -> None:
        command = self.runtime._build_llama_command(
            _base_payload(vendor="vulkan_pool", vram_ratios=[32000, 32000]),
            8101,
            99,
        )
        batch_idx = command.index("--batch-size")
        self.assertEqual(command[batch_idx + 1], "4096")
        ubatch_idx = command.index("--ubatch-size")
        self.assertEqual(command[ubatch_idx + 1], "512")

    def test_vulkan_env_sets_radv_perftest(self) -> None:
        env = self.runtime._build_env("vulkan", "vulkan:0", 8)
        self.assertEqual(env.get("RADV_PERFTEST"), "nogttspill")

    def test_main_gpu_emitted_for_pool_offload(self) -> None:
        command = self.runtime._build_llama_command(
            _base_payload(vendor="vulkan_pool", vram_ratios=[32000, 32000]),
            8101,
            99,
        )
        main_gpu_idx = command.index("--main-gpu")
        self.assertEqual(command[main_gpu_idx + 1], "0")


class BuildVendorArgsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = InferenceRuntime()

    def test_tensor_split_emitted_in_layer_mode_with_ratios(self) -> None:
        args = self.runtime._build_vendor_args("vulkan_pool", [32000, 32000], "layer")
        self.assertEqual(args, ["--tensor-split", "32000,32000", "--split-mode", "layer"])

    def test_non_pool_returns_empty(self) -> None:
        self.assertEqual(self.runtime._build_vendor_args("vulkan", [32000, 32000], "layer"), [])

    def test_pool_without_enough_ratios_omits_tensor_split(self) -> None:
        args = self.runtime._build_vendor_args("vulkan_pool", [32000], "layer")
        self.assertEqual(args, ["--split-mode", "layer"])


class ModelUpdateRequestBatchSizeTests(unittest.TestCase):
    def test_batch_size_below_minimum_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ModelUpdateRequest(batch_size=16)

    def test_batch_size_none_accepted(self) -> None:
        payload = ModelUpdateRequest(batch_size=None)
        self.assertIsNone(payload.batch_size)
        self.assertIn("batch_size", payload.model_fields_set)

    def test_explicit_null_tracked_in_model_fields_set(self) -> None:
        payload = ModelUpdateRequest.model_validate({"batch_size": None, "ubatch_size": None})
        self.assertIn("batch_size", payload.model_fields_set)
        self.assertIn("ubatch_size", payload.model_fields_set)


class InferenceManagerPayloadTests(unittest.IsolatedAsyncioTestCase):
    def _make_model(self, **kwargs) -> ModelConfig:
        defaults = {
            "id": 1,
            "file_name": "test.gguf",
            "model_dir_name": "test",
            "file_path": "/models/test/test.gguf",
            "alias": "test",
            "context_length": 8192,
            "threads": 8,
            "gpu_layers": 99,
            "batch_size": 16384,
            "ubatch_size": 2048,
        }
        defaults.update(kwargs)
        return ModelConfig(**defaults)

    def _make_device(self) -> Device:
        return Device(
            id=1,
            hardware_id="vulkan:0",
            stable_hardware_id="0000:03:00.0",
            vendor="vulkan",
            name="GPU 0",
            memory_mb=32000,
        )

    async def test_activate_model_payload_includes_batch_sizes(self) -> None:
        manager = InferenceManager()
        model = self._make_model()
        device = self._make_device()
        captured: dict = {}

        async def fake_post(url: str, json: dict | None = None, **kwargs):
            captured["json"] = json
            response = mock.Mock()
            response.is_error = False
            return response

        client = mock.AsyncMock()
        client.post = fake_post
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None

        with (
            mock.patch.object(manager, "runtime_url_for_vendor", return_value="http://inference"),
            mock.patch.object(manager, "_fetch_memory_metrics_with_gtt", return_value={}),
            mock.patch.object(manager, "wait_until_healthy", return_value=True),
            mock.patch("app.core.inference_manager.httpx.AsyncClient", return_value=client),
        ):
            await manager.activate_model(model, device)

        self.assertEqual(captured["json"]["batch_size"], 16384)
        self.assertEqual(captured["json"]["ubatch_size"], 2048)

    async def test_activate_model_on_pool_payload_includes_batch_sizes(self) -> None:
        manager = InferenceManager()
        model = self._make_model()
        devices = [self._make_device(), self._make_device()]
        devices[1].id = 2
        devices[1].hardware_id = "vulkan:1"
        devices[1].stable_hardware_id = "0000:04:00.0"
        target = PoolActivationTarget(
            pool_id=1,
            pool_name="test-pool",
            vendor="vulkan",
            devices=devices,
            split_mode="layer",
        )
        captured: dict = {}

        async def fake_post(url: str, json: dict | None = None, **kwargs):
            captured["json"] = json
            response = mock.Mock()
            response.is_error = False
            return response

        client = mock.AsyncMock()
        client.post = fake_post
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None

        with (
            mock.patch.object(manager, "runtime_url_for_vendor", return_value="http://inference"),
            mock.patch.object(manager, "_fetch_memory_metrics_with_gtt", return_value={}),
            mock.patch.object(manager, "wait_until_healthy", return_value=True),
            mock.patch("app.core.inference_manager.httpx.AsyncClient", return_value=client),
        ):
            await manager.activate_model_on_pool(model, target)

        self.assertEqual(captured["json"]["batch_size"], 16384)
        self.assertEqual(captured["json"]["ubatch_size"], 2048)
        self.assertEqual(captured["json"]["split_mode"], "layer")


if __name__ == "__main__":
    unittest.main()
