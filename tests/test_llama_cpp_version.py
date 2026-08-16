from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.core.llama_cpp_version import format_llama_cpp_release, read_llama_cpp_version


class LlamaCppVersionTests(unittest.TestCase):
    def test_prefers_tag_and_appends_distinct_commit(self) -> None:
        self.assertEqual(
            format_llama_cpp_release("b5592", "abcdef1234567890"),
            "b5592 (abcdef1)",
        )

    def test_does_not_duplicate_commit_when_tag_is_the_hash(self) -> None:
        self.assertEqual(format_llama_cpp_release("abcdef1", "abcdef1234567890"), "abcdef1")

    def test_falls_back_to_short_commit(self) -> None:
        self.assertEqual(format_llama_cpp_release("", "abcdef1234567890"), "abcdef1")

    def test_reads_build_files(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "BUILD_TAG").write_text("b5592\n", encoding="utf-8")
            (root / "BUILD_COMMIT").write_text("abcdef1234567890\n", encoding="utf-8")
            version = read_llama_cpp_version(root)
        self.assertEqual(version["llama_cpp_tag"], "b5592")
        self.assertEqual(version["llama_cpp_commit"], "abcdef1234567890")
        self.assertEqual(version["llama_cpp_release"], "b5592 (abcdef1)")


if __name__ == "__main__":
    unittest.main()
