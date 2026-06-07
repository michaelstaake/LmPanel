from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from app.core.gguf_shards import (
    build_shard_file_name,
    iter_model_gguf_files,
    parse_gguf_shard_name,
    resolve_primary_shard,
    strip_shard_suffix,
    validate_shard_set,
    validate_upload_shard_set,
)

QWEN_SHARD_1 = "Qwen3.6-35B-A3B-BF16-00001-of-00002.gguf"
QWEN_SHARD_2 = "Qwen3.6-35B-A3B-BF16-00002-of-00002.gguf"


class GgufShardUtilityTests(unittest.TestCase):
    def test_parse_qwen_shard_names(self) -> None:
        shard_1 = parse_gguf_shard_name(QWEN_SHARD_1)
        shard_2 = parse_gguf_shard_name(QWEN_SHARD_2)

        self.assertIsNotNone(shard_1)
        self.assertIsNotNone(shard_2)
        assert shard_1 is not None
        assert shard_2 is not None
        self.assertEqual(shard_1.prefix, "Qwen3.6-35B-A3B-BF16")
        self.assertEqual(shard_1.index, 1)
        self.assertEqual(shard_1.total, 2)
        self.assertEqual(shard_2.index, 2)

    def test_strip_shard_suffix(self) -> None:
        self.assertEqual(strip_shard_suffix(QWEN_SHARD_1), "Qwen3.6-35B-A3B-BF16")
        self.assertEqual(strip_shard_suffix("llama.gguf"), "llama")

    def test_resolve_primary_shard_prefers_first_part(self) -> None:
        model_dir = Path(tempfile.mkdtemp())
        shard_1 = model_dir / QWEN_SHARD_2
        shard_2 = model_dir / QWEN_SHARD_1
        shard_1.write_bytes(b"a")
        shard_2.write_bytes(b"b")

        primary = resolve_primary_shard([shard_1, shard_2])
        self.assertIsNotNone(primary)
        self.assertEqual(primary.name, QWEN_SHARD_1)

    def test_resolve_primary_shard_single_file(self) -> None:
        model_dir = Path(tempfile.mkdtemp())
        single = model_dir / "llama.gguf"
        single.write_bytes(b"a")

        primary = resolve_primary_shard([single])
        self.assertEqual(primary, single)

    def test_validate_shard_set_complete_and_missing(self) -> None:
        model_dir = Path(tempfile.mkdtemp())
        (model_dir / QWEN_SHARD_1).write_bytes(b"a")

        incomplete = validate_shard_set(model_dir, QWEN_SHARD_1)
        self.assertEqual(incomplete.total_shards, 2)
        self.assertFalse(incomplete.is_complete)
        self.assertEqual(incomplete.missing_names, [QWEN_SHARD_2])

        (model_dir / QWEN_SHARD_2).write_bytes(b"b")
        complete = validate_shard_set(model_dir, QWEN_SHARD_1)
        self.assertTrue(complete.is_complete)
        self.assertEqual(complete.present_shards, 2)

    def test_validate_upload_shard_set(self) -> None:
        primary, files = validate_upload_shard_set([QWEN_SHARD_1, QWEN_SHARD_2])
        self.assertEqual(primary, QWEN_SHARD_1)
        self.assertEqual(files, [QWEN_SHARD_1, QWEN_SHARD_2])

        primary_only, files = validate_upload_shard_set([QWEN_SHARD_1])
        self.assertEqual(primary_only, QWEN_SHARD_1)
        self.assertEqual(files, [QWEN_SHARD_1])

        with self.assertRaises(ValueError):
            validate_upload_shard_set([QWEN_SHARD_1, "llama.gguf"])

        with self.assertRaises(ValueError):
            validate_upload_shard_set([QWEN_SHARD_1, QWEN_SHARD_1])

    def test_build_shard_file_name(self) -> None:
        self.assertEqual(
            build_shard_file_name("Qwen3.6-35B-A3B-BF16", 2, 2),
            QWEN_SHARD_2,
        )


def _discover_model_files(models_dir: Path) -> list[tuple[str, str, Path]]:
    discovered: list[tuple[str, str, Path]] = []
    for child in sorted(models_dir.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir():
            continue
        gguf_files = iter_model_gguf_files(child)
        if not gguf_files:
            continue
        primary = resolve_primary_shard(gguf_files)
        if primary is None:
            continue
        discovered.append((child.name, primary.name, primary))
    return discovered


class GgufShardDiscoveryTests(unittest.TestCase):
    def test_discover_model_files_registers_primary_shard_only(self) -> None:
        with tempfile.TemporaryDirectory() as models_root:
            model_dir = Path(models_root) / "qwen-bf16"
            model_dir.mkdir()
            (model_dir / QWEN_SHARD_1).write_bytes(b"a")
            (model_dir / QWEN_SHARD_2).write_bytes(b"b")

            discovered = _discover_model_files(Path(models_root))
            self.assertEqual(len(discovered), 1)
            self.assertEqual(discovered[0][1], QWEN_SHARD_1)

    def test_discover_model_files_skips_incomplete_shard_directories(self) -> None:
        with tempfile.TemporaryDirectory() as models_root:
            model_dir = Path(models_root) / "qwen-bf16"
            model_dir.mkdir()
            (model_dir / QWEN_SHARD_2).write_bytes(b"b")

            discovered = _discover_model_files(Path(models_root))
            self.assertEqual(discovered, [])

    def test_validate_upload_rejects_partial_multi_file_set(self) -> None:
        with self.assertRaises(ValueError):
            validate_upload_shard_set([QWEN_SHARD_1, "llama.gguf"])


if __name__ == "__main__":
    unittest.main()
