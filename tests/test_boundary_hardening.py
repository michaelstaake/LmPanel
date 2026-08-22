import asyncio
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from fastapi.testclient import TestClient

from app.api.models import _normalize_fetch_url, _validate_public_fetch_url
from app.core.attachment_parser import extract_attachment_text
from app.inference_service import INFERENCE_SECRET_HEADER, _confine_model_path, app


class ModelFetchSsrfTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_loopback_and_private_ip_literals(self) -> None:
        for url in (
            "http://127.0.0.1/model.gguf",
            "http://10.0.0.1/model.gguf",
            "http://[::1]/model.gguf",
            "http://169.254.169.254/latest/model.gguf",
        ):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "non-public"):
                await _validate_public_fetch_url(url)

    async def test_rejects_hostname_if_any_dns_answer_is_private(self) -> None:
        records = [
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("127.0.0.1", 443)),
        ]
        loop = asyncio.get_running_loop()
        with mock.patch.object(loop, "getaddrinfo", return_value=records):
            with self.assertRaisesRegex(ValueError, "non-public"):
                await _validate_public_fetch_url("https://models.example/model.gguf")

    async def test_accepts_public_http_and_https_addresses(self) -> None:
        await _validate_public_fetch_url("https://8.8.8.8/model.gguf")
        await _validate_public_fetch_url("http://1.1.1.1/model.gguf")

    def test_signed_download_query_is_preserved(self) -> None:
        url = "https://example.com/model.gguf?token=abc#section"
        self.assertEqual(
            _normalize_fetch_url(url),
            "https://example.com/model.gguf?token=abc",
        )


class InferenceModelPathTests(unittest.TestCase):
    def test_accepts_existing_gguf_beneath_models_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model = root / "safe" / "model.gguf"
            model.parent.mkdir()
            model.write_bytes(b"GGUF")
            with mock.patch.dict(os.environ, {"MODELS_DIR": str(root)}):
                self.assertEqual(_confine_model_path(str(model), require_gguf=True), str(model.resolve()))

    def test_rejects_traversal_outside_models_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "models"
            root.mkdir()
            outside = base / "outside.gguf"
            outside.write_bytes(b"GGUF")
            with mock.patch.dict(os.environ, {"MODELS_DIR": str(root)}):
                with self.assertRaisesRegex(ValueError, "inside"):
                    _confine_model_path(str(root / ".." / "outside.gguf"), require_gguf=True)

    def test_rejects_non_gguf_primary_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model = root / "model.bin"
            model.write_bytes(b"data")
            with mock.patch.dict(os.environ, {"MODELS_DIR": str(root)}):
                with self.assertRaisesRegex(ValueError, "GGUF"):
                    _confine_model_path(str(model), require_gguf=True)


class InferenceAuthenticationTests(unittest.TestCase):
    def test_shared_secret_rejects_missing_header(self) -> None:
        with (
            mock.patch.dict(os.environ, {"INFERENCE_SHARED_SECRET": "test-secret"}),
            TestClient(app) as client,
        ):
            response = client.post("/runtime/models/123/deactivate")
        self.assertEqual(response.status_code, 401)

    def test_shared_secret_accepts_matching_header(self) -> None:
        with (
            mock.patch.dict(os.environ, {"INFERENCE_SHARED_SECRET": "test-secret"}),
            TestClient(app) as client,
        ):
            response = client.post(
                "/runtime/models/123/deactivate",
                headers={INFERENCE_SECRET_HEADER: "test-secret"},
            )
        self.assertEqual(response.status_code, 200)


class AttachmentLimitTests(unittest.TestCase):
    def test_rejects_high_ratio_archive(self) -> None:
        payload = BytesIO()
        with ZipFile(payload, "w", ZIP_DEFLATED) as archive:
            archive.writestr("content.xml", b"A" * (1024 * 1024))

        result = extract_attachment_text("bomb.odt", None, payload.getvalue())
        self.assertEqual(result["status"], "error")
        self.assertIn("compression ratio", result["detail"])

    def test_rejects_xml_entity_declarations(self) -> None:
        content = b'<!DOCTYPE x [<!ENTITY x "boom">]><root>&x;</root>'
        payload = BytesIO()
        with ZipFile(payload, "w", ZIP_STORED) as archive:
            archive.writestr("content.xml", content)

        result = extract_attachment_text("entity.odt", None, payload.getvalue())
        self.assertEqual(result["status"], "error")
        self.assertIn("entity declarations", result["detail"])


if __name__ == "__main__":
    unittest.main()
