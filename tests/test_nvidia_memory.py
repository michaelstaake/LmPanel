"""Tests for NVIDIA GPU memory metrics via nvidia-smi."""

import unittest
from unittest.mock import patch, MagicMock

from app.core.nvidia_memory import (
    map_vulkan_index_to_nvidia_index,
    normalize_pci_bdf,
    nvidia_smi_bdf_by_index,
    read_nvidia_gpu_usage,
    read_nvidia_memory_metrics,
)

MOCK_SUBPROCESS = "app.core.nvidia_memory.subprocess"


class NormalizePciBdfTests(unittest.TestCase):
    def test_full_bdf(self):
        self.assertEqual(normalize_pci_bdf("0000:01:00.0"), "0000:01:00.0")

    def test_short_bdf_no_domain(self):
        self.assertEqual(normalize_pci_bdf("01:00.0"), "0000:01:00.0")

    def test_bdf_no_function(self):
        self.assertEqual(normalize_pci_bdf("0000:01:00"), "0000:01:00.0")

    def test_uppercase(self):
        self.assertEqual(normalize_pci_bdf("0000:0A:0B.1"), "0000:0a:0b.1")

    def test_invalid(self):
        self.assertIsNone(normalize_pci_bdf("not-a-bdf"))


class ReadNvidiaMemoryMetricsTests(unittest.TestCase):
    def test_normal_output(self):
        with patch(f"{MOCK_SUBPROCESS}.check_output", return_value="16384,    8192\n"):
            result = read_nvidia_memory_metrics(0)
        self.assertEqual(result["memory_total_mb"], 16384)
        self.assertEqual(result["memory_used_mb"], 8192)
        self.assertEqual(result["memory_source"], "nvidia-smi")

    def test_zero_usage(self):
        with patch(f"{MOCK_SUBPROCESS}.check_output", return_value="24576,    0\n"):
            result = read_nvidia_memory_metrics(0)
        self.assertEqual(result["memory_total_mb"], 24576)
        self.assertEqual(result["memory_used_mb"], 0)

    def test_subprocess_failure(self):
        with patch(f"{MOCK_SUBPROCESS}.check_output", side_effect=Exception("not found")):
            result = read_nvidia_memory_metrics(0)
        self.assertEqual(result, {})

    def test_malformed_output(self):
        with patch(f"{MOCK_SUBPROCESS}.check_output", return_value="garbage"):
            result = read_nvidia_memory_metrics(0)
        self.assertEqual(result, {})

    def test_calls_correct_index(self):
        with patch(f"{MOCK_SUBPROCESS}.check_output", return_value="8192,    1024\n") as mock:
            read_nvidia_memory_metrics(2)
        mock.assert_called_once()
        args = mock.call_args[0][0]
        self.assertIn("-i", args)
        self.assertIn("2", args)


class ReadNvidiaGpuUsageTests(unittest.TestCase):
    def test_normal_output(self):
        with patch(f"{MOCK_SUBPROCESS}.check_output", return_value="75\n"):
            result = read_nvidia_gpu_usage(0)
        self.assertEqual(result, 75)

    def test_subprocess_failure(self):
        with patch(f"{MOCK_SUBPROCESS}.check_output", side_effect=Exception("not found")):
            result = read_nvidia_gpu_usage(0)
        self.assertIsNone(result)

    def test_malformed_output(self):
        with patch(f"{MOCK_SUBPROCESS}.check_output", return_value="abc\n"):
            result = read_nvidia_gpu_usage(0)
        self.assertIsNone(result)


class NvidiaSmiBdfByIndexTests(unittest.TestCase):
    def test_multiple_gpus(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "0000:01:00.0\n0000:02:00.0\n0000:03:00.0\n"
        with patch(f"{MOCK_SUBPROCESS}.run", return_value=mock_result):
            result = nvidia_smi_bdf_by_index()
        self.assertEqual(result[0], "0000:01:00.0")
        self.assertEqual(result[1], "0000:02:00.0")
        self.assertEqual(result[2], "0000:03:00.0")

    def test_subprocess_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with patch(f"{MOCK_SUBPROCESS}.run", return_value=mock_result):
            result = nvidia_smi_bdf_by_index()
        self.assertEqual(result, {})


class MapVulkanIndexToNvidiaIndexTests(unittest.TestCase):
    def test_matching_bdf(self):
        bdf_map = {0: "0000:01:00.0", 1: "0000:02:00.0"}
        result = map_vulkan_index_to_nvidia_index("0000:02:00.0", bdf_map)
        self.assertEqual(result, 1)

    def test_no_match(self):
        bdf_map = {0: "0000:01:00.0"}
        result = map_vulkan_index_to_nvidia_index("0000:99:00.0", bdf_map)
        self.assertIsNone(result)

    def test_empty_map(self):
        result = map_vulkan_index_to_nvidia_index("0000:01:00.0", {})
        self.assertIsNone(result)

    def test_unnormalized_vulkan_bdf(self):
        bdf_map = {0: "0000:01:00.0"}
        result = map_vulkan_index_to_nvidia_index("01:00.0", bdf_map)
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
