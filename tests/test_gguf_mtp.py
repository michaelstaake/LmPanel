import struct
import tempfile
import unittest
from pathlib import Path

from app.core.gguf import gguf_supports_mtp, read_gguf_mtp_layer_count


def _write_gguf(path: Path, metadata: list[tuple[str, object]]) -> None:
    payload = bytearray()
    payload.extend(b"GGUF")
    payload.extend(struct.pack("<I", 3))
    payload.extend(struct.pack("<Q", 0))
    payload.extend(struct.pack("<Q", len(metadata)))
    for key, value in metadata:
        encoded_key = key.encode("utf-8")
        payload.extend(struct.pack("<Q", len(encoded_key)))
        payload.extend(encoded_key)
        if isinstance(value, str):
            encoded = value.encode("utf-8")
            payload.extend(struct.pack("<I", 8))
            payload.extend(struct.pack("<Q", len(encoded)))
            payload.extend(encoded)
        elif isinstance(value, int):
            payload.extend(struct.pack("<I", 10))
            payload.extend(struct.pack("<Q", value))
        else:
            raise TypeError(type(value))
    path.write_bytes(payload)


class GgufMtpDetectionTests(unittest.TestCase):
    def test_detects_nextn_predict_layers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "qwen.gguf"
            _write_gguf(
                path,
                [
                    ("general.architecture", "qwen35"),
                    ("qwen35.nextn_predict_layers", 1),
                ],
            )
            self.assertEqual(read_gguf_mtp_layer_count(str(path)), 1)
            self.assertTrue(gguf_supports_mtp(str(path)))

    def test_zero_nextn_is_not_mtp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plain.gguf"
            _write_gguf(
                path,
                [
                    ("general.architecture", "qwen35"),
                    ("qwen35.nextn_predict_layers", 0),
                ],
            )
            self.assertEqual(read_gguf_mtp_layer_count(str(path)), 0)
            self.assertFalse(gguf_supports_mtp(str(path)))

    def test_filename_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Qwen3.6-27B-Q4_K_M-mtp.gguf"
            _write_gguf(path, [("general.architecture", "qwen35")])
            self.assertTrue(gguf_supports_mtp(str(path)))
