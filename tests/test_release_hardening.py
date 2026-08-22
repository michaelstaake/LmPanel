from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import auth
from app.core.config import Settings
from app.core.db import Base, get_db
from app.core.installation import acquire_setup_claim, ensure_public_storage
from app.core.security import hash_password
from app.models.user import User
from app.utils.schemas import ProfileUpdateRequest


class PublicStorageTests(unittest.TestCase):
    def test_only_public_data_is_served_and_legacy_branding_is_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_dir = Path(temporary_directory)
            (data_dir / "lmpanel.db").write_text("sensitive", encoding="utf-8")
            (data_dir / "lmpanel.db-wal").write_text("sensitive", encoding="utf-8")
            (data_dir / ".jwt-secret").write_text("secret", encoding="utf-8")
            (data_dir / ".setup-complete").write_text("complete", encoding="utf-8")
            private_key = data_dir / "letsencrypt" / "live" / "example.com" / "privkey.pem"
            private_key.parent.mkdir(parents=True)
            private_key.write_text("private", encoding="utf-8")
            cloudflare_credentials = data_dir / "letsencrypt" / "cloudflare.ini"
            cloudflare_credentials.write_text("token", encoding="utf-8")
            (data_dir / "favicons").mkdir()
            (data_dir / "favicons" / "brand.png").write_bytes(b"png")
            (data_dir / "logos").mkdir()
            (data_dir / "logos" / "brand.svg").write_text("<svg/>", encoding="utf-8")

            public_dir = ensure_public_storage(str(data_dir))
            app = FastAPI()
            app.mount("/static", StaticFiles(directory=public_dir), name="static")
            client = TestClient(app)

            self.assertEqual(client.get("/static/favicons/brand.png").content, b"png")
            self.assertEqual(client.get("/static/logos/brand.svg").status_code, 200)
            self.assertEqual(client.get("/static/lmpanel.db").status_code, 404)
            self.assertEqual(client.get("/static/lmpanel.db-wal").status_code, 404)
            self.assertEqual(client.get("/static/.jwt-secret").status_code, 404)
            self.assertEqual(client.get("/static/.setup-complete").status_code, 404)
            self.assertEqual(client.get("/static/letsencrypt/live/example.com/privkey.pem").status_code, 404)
            self.assertEqual(client.get("/static/letsencrypt/cloudflare.ini").status_code, 404)


class InstallationSecretTests(unittest.TestCase):
    def test_default_jwt_secret_is_random_and_persistent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            first = Settings(data_dir=temporary_directory, jwt_secret="")
            second = Settings(data_dir=temporary_directory, jwt_secret="change-me")

            self.assertEqual(first.jwt_secret, second.jwt_secret)
            self.assertNotEqual(first.jwt_secret, "change-me")
            self.assertGreaterEqual(len(first.jwt_secret), 32)

    def test_setup_claim_is_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            claim = acquire_setup_claim(temporary_directory)
            with self.assertRaises(RuntimeError):
                acquire_setup_claim(temporary_directory)
            claim.unlink()
            replacement = acquire_setup_claim(temporary_directory)
            replacement.unlink()

    def test_explicit_short_jwt_secret_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(ValueError, "at least 32 characters"):
                Settings(data_dir=temporary_directory, jwt_secret="too-short")


class AuthHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "test.db"
        self.engine = create_engine(
            f"sqlite:///{database_path}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.settings = SimpleNamespace(
            data_dir=self.temporary_directory.name,
            setup_token="one-time-setup-token",
            app_port=8444,
            app_external_port=0,
        )

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temporary_directory.cleanup()

    def _client(self) -> TestClient:
        app = FastAPI()
        app.include_router(auth.router)

        def override_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        return TestClient(app)

    def test_remote_bootstrap_requires_token_and_can_only_run_once(self) -> None:
        payload = {
            "username": "admin",
            "email": "admin@localhost",
            "password": "password123",
        }
        with (
            patch.object(auth, "get_settings", return_value=self.settings),
            patch.object(auth, "scan_models_dir"),
            patch.object(auth, "log_event"),
        ):
            client = self._client()
            self.assertEqual(client.post("/api/auth/bootstrap-admin", json=payload).status_code, 403)

            payload["setup_token"] = "one-time-setup-token"
            response = client.post("/api/auth/bootstrap-admin", json=payload)
            self.assertEqual(response.status_code, 200)

            payload["username"] = "otheradmin"
            payload["email"] = "other@localhost"
            self.assertEqual(client.post("/api/auth/bootstrap-admin", json=payload).status_code, 409)

        db = self.session_factory()
        try:
            self.assertEqual(db.query(User).count(), 1)
        finally:
            db.close()

    def test_local_setup_check_ignores_spoofable_forwarding_headers(self) -> None:
        local_request = SimpleNamespace(
            headers={"x-forwarded-for": "203.0.113.10"},
            client=SimpleNamespace(host="127.0.0.1"),
        )
        remote_request = SimpleNamespace(
            headers={"x-forwarded-for": "127.0.0.1"},
            client=SimpleNamespace(host="172.18.0.2"),
        )

        self.assertTrue(auth._is_local_request(local_request))
        self.assertFalse(auth._is_local_request(remote_request))

    def test_profile_update_preserves_terms_accepted_state(self) -> None:
        db = self.session_factory()
        user = User(
            username="testuser",
            email="old@example.com",
            password_hash="unused",
            is_admin=False,
            is_active=True,
            terms_accepted_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))

        with patch.object(auth, "log_event"):
            response = auth.update_current_user(
                ProfileUpdateRequest(email="new@example.com"),
                request,
                user,
                db,
            )

        self.assertTrue(response.terms_accepted)
        db.close()

    def test_password_change_requires_current_password_and_revokes_sessions(self) -> None:
        db = self.session_factory()
        user = User(
            username="passworduser",
            email="password@example.com",
            password_hash=hash_password("old-password"),
            is_admin=False,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))

        with patch.object(auth, "log_event"):
            with self.assertRaisesRegex(HTTPException, "Current password is incorrect"):
                auth.update_current_user(
                    ProfileUpdateRequest(password="new-password", current_password="wrong"),
                    request,
                    user,
                    db,
                )
            response = auth.update_current_user(
                ProfileUpdateRequest(password="new-password", current_password="old-password"),
                request,
                user,
                db,
            )

        self.assertEqual(user.token_version, 1)
        self.assertTrue(response.terms_accepted is False)
        db.close()


if __name__ == "__main__":
    unittest.main()
