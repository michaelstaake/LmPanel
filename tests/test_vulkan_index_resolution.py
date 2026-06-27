import os
import unittest
from unittest import mock

for _env_key in (
    "STARTUP_HEALTHCHECK_INTERVAL",
    "STARTUP_HEALTHCHECK_TIMEOUT",
    "STARTUP_HEALTHCHECK_RETRIES",
    "STARTUP_HEALTHCHECK_START_PERIOD",
    "LLAMA_CPP_TAG",
):
    os.environ.pop(_env_key, None)

from app.core.device_manager import parse_vulkaninfo_bdf_by_index, vulkaninfo_index_by_bdf
from app.inference_service import InferenceRuntime

# GPU0 and GPU1 with PCI addresses in an order that does NOT match index order, so a
# naive index-based mapping would land on the wrong card.
SAMPLE_VULKANINFO = """
GPU0:
\tdeviceName = Card At 65
\tpciBusInfo = 0000:65:00.0
GPU1:
\tdeviceName = Card At 03
\tpciBusInfo = 0000:03:00.0
"""


class VulkaninfoParsingTests(unittest.TestCase):
    def test_bdf_by_index(self) -> None:
        self.assertEqual(
            parse_vulkaninfo_bdf_by_index(SAMPLE_VULKANINFO),
            {0: "0000:65:00.0", 1: "0000:03:00.0"},
        )

    def test_index_by_bdf_is_inverse(self) -> None:
        self.assertEqual(
            vulkaninfo_index_by_bdf(SAMPLE_VULKANINFO),
            {"0000:65:00.0": 0, "0000:03:00.0": 1},
        )


class ResolveVulkanIndicesTests(unittest.TestCase):
    def _runtime(self) -> InferenceRuntime:
        return InferenceRuntime()

    def test_resolves_live_index_from_stable_bdf(self) -> None:
        runtime = self._runtime()
        with mock.patch.object(InferenceRuntime, "_run_command", return_value=SAMPLE_VULKANINFO):
            # Stored hardware_id says vulkan:1 but the device's stable BDF is the card
            # currently enumerated at live index 0 -> must resolve to "0".
            indices = runtime._resolve_vulkan_indices(["vulkan:1"], ["0000:65:00.0"])
        self.assertEqual(indices, ["0"])

    def test_pool_resolves_each_member_by_bdf(self) -> None:
        runtime = self._runtime()
        with mock.patch.object(InferenceRuntime, "_run_command", return_value=SAMPLE_VULKANINFO):
            indices = runtime._resolve_vulkan_indices(
                ["vulkan:0", "vulkan:1"],
                ["0000:03:00.0", "0000:65:00.0"],
            )
        # 0000:03:00.0 is live index 1, 0000:65:00.0 is live index 0.
        self.assertEqual(indices, ["1", "0"])

    def test_falls_back_to_embedded_index_without_bdf(self) -> None:
        runtime = self._runtime()
        with mock.patch.object(InferenceRuntime, "_run_command", return_value=SAMPLE_VULKANINFO):
            indices = runtime._resolve_vulkan_indices(["vulkan:2"], [""])
        self.assertEqual(indices, ["2"])

    def test_build_env_sets_visible_devices_from_bdf(self) -> None:
        runtime = self._runtime()
        with mock.patch.object(InferenceRuntime, "_run_command", return_value=SAMPLE_VULKANINFO):
            env = runtime._build_env(
                "vulkan",
                "vulkan:1",
                threads=8,
                stable_hardware_id="0000:65:00.0",
            )
        self.assertEqual(env["GGML_VK_VISIBLE_DEVICES"], "0")


if __name__ == "__main__":
    unittest.main()
