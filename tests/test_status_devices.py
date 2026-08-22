"""Tests for /api/status device visibility."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import status
from app.api.deps import get_current_user
from app.core.db import Base, get_db
from app.core.inference_manager import InferenceManager
from app.models.device import Device
from app.models.user import User
import app.models  # noqa: F401 — register metadata


class StatusDevicesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        self.db: Session = self.SessionLocal()

        self.user = User(
            username="status-user",
            email="status@example.com",
            password_hash="x",
            is_admin=True,
            is_active=True,
        )
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

        available = Device(
            hardware_id="vulkan:0",
            name="Active GPU",
            vendor="vulkan",
            device_type="gpu",
            memory_mb=32000,
            enabled=True,
            available=True,
            priority=10,
        )
        removed = Device(
            hardware_id="vulkan:1",
            name="Removed GPU",
            vendor="vulkan",
            device_type="gpu",
            memory_mb=32000,
            enabled=True,
            available=False,
            priority=20,
        )
        self.db.add_all([available, removed])
        self.db.commit()

        app = FastAPI()
        status.router.inference_manager = InferenceManager()  # type: ignore[attr-defined]
        app.include_router(status.router)

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    @patch("app.api.status._fetch_llama_cpp_release", new_callable=AsyncMock, return_value=None)
    @patch("app.api.status._fetch_runtime_devices", new_callable=AsyncMock, return_value=({}, {}, []))
    def test_omits_soft_disabled_devices(self, _runtime_devices, _llama_release) -> None:
        response = self.client.get("/api/status")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        hardware_ids = {row["hardware_id"] for row in payload["devices"]}
        self.assertEqual(hardware_ids, {"vulkan:0"})
        self.assertTrue(all(row["available"] for row in payload["devices"]))


if __name__ == "__main__":
    unittest.main()
