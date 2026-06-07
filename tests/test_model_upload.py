"""Tests for GGUF model upload streaming."""

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


class ModelUploadTests(unittest.TestCase):
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

    def test_upload_model_streams_to_models_dir(self) -> None:
        content = _make_gguf_bytes()
        response = self.client.post(
            "/api/models/upload",
            headers={"Authorization": f"Bearer {self.token}"},
            files={"file": ("test-model-Q4_K_M.gguf", io.BytesIO(content), "application/octet-stream")},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload.get("status"), "ok")
        task_id = payload.get("task_id")
        self.assertTrue(task_id)

        task = task_manager.get_tasks(include_finished=True)
        matching = [entry for entry in task if entry["task_id"] == task_id]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["status"], "completed")

        db = self.session_factory()
        try:
            model = db.query(ModelConfig).filter(ModelConfig.file_name == "test-model-Q4_K_M.gguf").first()
            self.assertIsNotNone(model)
            assert model is not None
            saved_path = Path(model.file_path)
            self.assertTrue(saved_path.is_file())
            self.assertEqual(saved_path.read_bytes(), content)
            self.assertEqual(saved_path.parent.parent, self.models_dir)
        finally:
            db.close()
