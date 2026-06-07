"""Tests for direct multipart model upload streaming."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from starlette.requests import Request

from app.core.model_upload_stream import ModelMultipartUploadParser


class ModelUploadStreamTests(unittest.TestCase):
    def test_parser_writes_file_directly_to_disk(self) -> None:
        boundary = "----boundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="test.gguf"\r\n'
            "Content-Type: application/octet-stream\r\n"
            "\r\n"
            "GGUFDATA\r\n"
            f"--{boundary}--\r\n"
        ).encode()

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [(b"content-type", f"multipart/form-data; boundary={boundary}".encode())],
        }
        request = Request(scope, receive)

        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp)
            parser = ModelMultipartUploadParser(
                request.headers,
                request.stream(),
                model_dir=model_dir,
                max_bytes=1024 * 1024,
                on_progress=lambda _written: None,
            )
            result = asyncio.run(parser.parse())
            self.assertEqual(len(result.files), 1)
            saved = result.files[0].destination
            self.assertTrue(saved.is_file())
            self.assertEqual(saved.read_bytes(), b"GGUFDATA")


if __name__ == "__main__":
    unittest.main()
