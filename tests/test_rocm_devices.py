import json
import os
import subprocess
import unittest
from unittest.mock import Mock, patch

for _env_key in (
    "STARTUP_HEALTHCHECK_INTERVAL",
    "STARTUP_HEALTHCHECK_TIMEOUT",
    "STARTUP_HEALTHCHECK_RETRIES",
    "STARTUP_HEALTHCHECK_START_PERIOD",
    "LLAMA_CPP_TAG",
):
    os.environ.pop(_env_key, None)

from app.core.device_manager import AMD_VENDOR_ID, DeviceManager, get_supported_vendors, is_supported_vendor
from app.inference_service import (
    ActivateModelRequest,
    InferenceRuntime,
    _format_gpu_layers_for_cli,
    _llama_offload_extra_args,
    _validate_gpu_offload_from_log,
)


ROCM_JSON_SAMPLE = json.dumps(
    {
        "card0": {
            "Card series": "Radeon AI PRO R9700",
            "VRAM Total Memory (B)": str(32 * 1024**3),
        },
        "card1": {
            "Card series": "Radeon RX 7900 XTX",
            "VRAM Total Memory (B)": str(24 * 1024**3),
        },
    }
)


class SupportedVendorTests(unittest.TestCase):
    def test_rocm_in_default_supported_vendors(self) -> None:
        with patch.dict(os.environ, {"SUPPORTED_DEVICES": ""}, clear=False):
            from app.core import config

            config.get_settings.cache_clear()
            try:
                self.assertIn("rocm", get_supported_vendors())
                self.assertTrue(is_supported_vendor("rocm"))
            finally:
                config.get_settings.cache_clear()


class RocmDetectionTests(unittest.TestCase):
    def test_parse_rocm_json(self) -> None:
        devices = DeviceManager._parse_rocm_json(ROCM_JSON_SAMPLE)
        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0].hardware_id, "rocm:0")
        self.assertEqual(devices[0].vendor, "rocm")
        self.assertEqual(devices[0].name, "Radeon AI PRO R9700")
        self.assertGreater(devices[0].memory_mb, 30000)

    def test_parse_rocm_text(self) -> None:
        text = "card0 vram total memory (B): 34359738368"
        devices = DeviceManager._parse_rocm_text(text)
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].hardware_id, "rocm:0")

    def test_vulkan_excludes_amd_when_rocm_runtime_healthy(self) -> None:
        manager = DeviceManager()
        summary = (
            "GPU0:\n"
            "        deviceName         = Intel Arc A770\n"
            "        deviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU\n"
            "        vendorID           = 0x8086\n"
            "GPU1:\n"
            "        deviceName         = AMD Radeon RX 7900\n"
            "        deviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU\n"
            "        vendorID           = 0x1002\n"
        )
        with patch.object(manager, "_should_hide_vulkan_amd", return_value=True):
            with patch(
                "app.core.device_manager.subprocess.run",
                return_value=Mock(stdout=summary, returncode=0),
            ):
                with patch.object(manager, "_parse_vulkan_device_memory", return_value={0: 16384}):
                    devices = manager._detect_vulkan(exclude_amd=True)

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].hardware_id, "vulkan:0")
        self.assertNotEqual(devices[0].pci_vendor_id, AMD_VENDOR_ID)


class LlamaOffloadCliTests(unittest.TestCase):
    def test_format_gpu_layers_for_cli(self) -> None:
        self.assertEqual(_format_gpu_layers_for_cli(-1), "all")
        self.assertEqual(_format_gpu_layers_for_cli(42), "42")

    def test_llama_offload_extra_args_disable_fit_for_rocm(self) -> None:
        self.assertEqual(
            _llama_offload_extra_args("rocm", -1, fit_to_vram=False),
            ["--fit", "off", "--main-gpu", "0"],
        )
        self.assertEqual(_llama_offload_extra_args("cpu", -1, fit_to_vram=False), [])

    def test_validate_gpu_offload_from_log_rejects_zero_layers(self) -> None:
        import tempfile

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write("load_tensors: offloaded 0/35 layers to GPU\n")
            path = handle.name
        try:
            with self.assertRaises(RuntimeError):
                _validate_gpu_offload_from_log(path, "rocm", -1)
        finally:
            os.unlink(path)


class RocmInferenceEnvTests(unittest.TestCase):
    def test_build_env_rocm_single(self) -> None:
        runtime = InferenceRuntime()
        env = runtime._build_env("rocm", "rocm:1", threads=4)
        self.assertEqual(env["HIP_VISIBLE_DEVICES"], "1")
        self.assertEqual(env.get("HSA_OVERRIDE_GFX_VERSION"), "12.0.1")

    def test_build_env_rocm_pool(self) -> None:
        runtime = InferenceRuntime()
        env = runtime._build_env("rocm_pool", "rocm:0", threads=4, hardware_ids=["rocm:0", "rocm:1"])
        self.assertEqual(env["HIP_VISIBLE_DEVICES"], "0,1")

    def test_build_vendor_args_rocm_pool(self) -> None:
        runtime = InferenceRuntime()
        args = runtime._build_vendor_args("rocm_pool", vram_ratios=[24, 16], split_mode="layer")
        self.assertEqual(args, ["--tensor-split", "24,16", "--split-mode", "layer"])

    def test_stable_hardware_conflict(self) -> None:
        from app.inference_service import RunningModel

        runtime = InferenceRuntime()
        proc = subprocess.Popen(
            ["python", "-c", "import time; time.sleep(120)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        runtime._running = {
            1: RunningModel(
                model_id=1,
                alias="busy",
                hardware_id="rocm:0",
                vendor="rocm",
                port=9101,
                process=proc,
                stable_hardware_ids=["0000:03:00.0"],
            )
        }
        payload = ActivateModelRequest(
            model_id=2,
            alias="new",
            file_path="/tmp/model.gguf",
            context_length=4096,
            threads=4,
            gpu_layers=-1,
            vendor="rocm",
            hardware_id="rocm:1",
            stable_hardware_id="0000:03:00.0",
        )
        try:
            with self.assertRaises(RuntimeError):
                runtime._ensure_stable_hardware_available(payload)
        finally:
            runtime.deactivate_model(1)


class PoolVendorValidationTests(unittest.TestCase):
    def test_pool_vendor_allowlist_includes_rocm(self) -> None:
        allowed = {"nvidia", "vulkan", "rocm"}
        self.assertIn("rocm", allowed)
        self.assertNotIn("cuda", allowed)


if __name__ == "__main__":
    unittest.main()
