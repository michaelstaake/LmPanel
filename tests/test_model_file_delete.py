"""Tests for deleting additional model asset files."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import models as models_api
from app.api.deps import get_admin_user, get_db
from app.core import config
from app.core.db import Base
from app.core.security import create_access_token
from app.core.task_manager import task_manager
from app.models.model_config import ModelConfig
from app.models.user import User


def _make_gguf_bytes(size: int = 128) -> bytes:
    return b"GGUF" + b"\x00" * (size - 4)


class ModelFileDeleteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.models_dir = Path(self.temp_dir.name) / "models"
        self.models_dir.mkdir()
        self.env_patch = patch.dict(
            os.environ,
            {
                "MODELS_DIR": str(self.models_dir),
                "DATABASE_URL": "sqlite:///:memory:",
                "DATA_DIR": str(Path(self.temp_dir.name) / "data"),
            },
            clear=False,
        )
        self.env_patch.start()
        config.get_settings.cache_clear()

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(engine)
        self.engine = engine
        self.session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        db = self.session_factory()
        self.admin_user = User(
            username="admin",
            email="admin@test",
            password_hash="hash",
            is_admin=True,
            is_active=True,
        )
        db.add(self.admin_user)
        db.commit()
        db.refresh(self.admin_user)
        db.close()

        app = FastAPI()
        app.include_router(models_api.router)

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_admin_user] = lambda: self.admin_user
        self.client = TestClient(app)
        self.token = create_access_token(self.admin_user.username)

    def tearDown(self) -> None:
        self.client.close()
        self.engine.dispose()
        self.env_patch.stop()
        config.get_settings.cache_clear()
        task_manager._tasks.clear()
        task_manager._async_tasks.clear()
        self.temp_dir.cleanup()

    def _create_model(self, *, vision_enabled: bool = False) -> ModelConfig:
        model_dir = self.models_dir / "test-model"
        model_dir.mkdir()
        primary_name = "test-model-Q4_K_M.gguf"
        mmproj_name = "mmproj-test-model-f16.gguf"
        (model_dir / primary_name).write_bytes(_make_gguf_bytes())
        (model_dir / mmproj_name).write_bytes(_make_gguf_bytes())
        (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")

        db = self.session_factory()
        try:
            model = ModelConfig(
                priority=0,
                file_name=primary_name,
                model_dir_name="test-model",
                file_path=str((model_dir / primary_name).resolve()),
                alias="test-model",
                vision_enabled=vision_enabled,
                mmproj_file_name=mmproj_name,
            )
            db.add(model)
            db.commit()
            db.refresh(model)
            return model
        finally:
            db.close()

    def test_delete_additional_file(self) -> None:
        model = self._create_model()
        response = self.client.delete(
            f"/api/models/{model.id}/files/tokenizer.json",
            headers={"Authorization": f"Bearer {self.token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload.get("deleted"), "tokenizer.json")
        self.assertFalse((self.models_dir / "test-model" / "tokenizer.json").exists())
        self.assertIn("directory_files", payload["model"])
        self.assertEqual(
            [entry["name"] for entry in payload["model"]["directory_files"]],
            ["mmproj-test-model-f16.gguf", "test-model-Q4_K_M.gguf"],
        )

    def test_delete_mmproj_updates_metadata(self) -> None:
        model = self._create_model()
        response = self.client.delete(
            f"/api/models/{model.id}/files/mmproj-test-model-f16.gguf",
            headers={"Authorization": f"Bearer {self.token}"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertIsNone(payload["model"]["mmproj_file_name"])

        db = self.session_factory()
        try:
            refreshed = db.query(ModelConfig).filter(ModelConfig.id == model.id).first()
            self.assertIsNotNone(refreshed)
            assert refreshed is not None
            self.assertIsNone(refreshed.mmproj_file_name)
        finally:
            db.close()

    def test_cannot_delete_primary_file(self) -> None:
        model = self._create_model()
        response = self.client.delete(
            f"/api/models/{model.id}/files/{model.file_name}",
            headers={"Authorization": f"Bearer {self.token}"},
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("primary model file", response.json()["detail"].lower())

    def test_cannot_delete_mmproj_when_vision_enabled(self) -> None:
        model = self._create_model(vision_enabled=True)
        response = self.client.delete(
            f"/api/models/{model.id}/files/mmproj-test-model-f16.gguf",
            headers={"Authorization": f"Bearer {self.token}"},
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("vision", response.json()["detail"].lower())

    def test_cannot_delete_file_when_model_activated(self) -> None:
        model = self._create_model()
        db = self.session_factory()
        try:
            stored = db.query(ModelConfig).filter(ModelConfig.id == model.id).first()
            assert stored is not None
            stored.activated = True
            db.add(stored)
            db.commit()
        finally:
            db.close()

        response = self.client.delete(
            f"/api/models/{model.id}/files/tokenizer.json",
            headers={"Authorization": f"Bearer {self.token}"},
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("disable this model", response.json()["detail"].lower())

    def test_upload_then_delete_additional_file(self) -> None:
        model = self._create_model()
        upload_response = self.client.post(
            f"/api/models/{model.id}/files",
            headers={"Authorization": f"Bearer {self.token}"},
            files={"files": ("extra-config.yaml", io.BytesIO(b"key: value\n"), "application/octet-stream")},
        )
        self.assertEqual(upload_response.status_code, 200, upload_response.text)

        delete_response = self.client.delete(
            f"/api/models/{model.id}/files/extra-config.yaml",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(delete_response.status_code, 200, delete_response.text)
        self.assertFalse((self.models_dir / "test-model" / "extra-config.yaml").exists())


if __name__ == "__main__":
    unittest.main()
