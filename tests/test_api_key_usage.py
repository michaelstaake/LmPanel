"""Tests for per-API-key token usage tracking and /v1/usage/{timeframe}."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import openai_compat
from app.api.deps import require_api_key_access
from app.core.db import Base, get_db
from app.core.security import generate_api_key, hash_api_key
from app.core.token_usage import USAGE_TIMEFRAMES, get_api_key_token_total, record_token_usage
from app.models.api_key import ApiKey
from app.models.token_usage import TokenUsage
from app.models.user import User
import app.models  # noqa: F401 — register metadata


class ApiKeyTokenUsageTests(unittest.TestCase):
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
            username="usage-user",
            email="usage@example.com",
            password_hash="x",
            is_admin=False,
            is_active=True,
        )
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

        self.plain_key = generate_api_key()
        self.api_key = ApiKey(user_id=self.user.id, name="test", key_hash=hash_api_key(self.plain_key))
        self.db.add(self.api_key)
        self.db.commit()
        self.db.refresh(self.api_key)

        other_key = ApiKey(user_id=self.user.id, name="other", key_hash=hash_api_key(generate_api_key()))
        self.db.add(other_key)
        self.db.commit()
        self.db.refresh(other_key)
        self.other_key_id = other_key.id

        app = FastAPI()
        app.include_router(openai_compat.router)

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[require_api_key_access] = lambda: (self.user, self.api_key.id)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_record_token_usage_stores_api_key_id(self) -> None:
        recorded = record_token_usage(
            self.db,
            user_id=self.user.id,
            api_key_id=self.api_key.id,
            total_tokens=42,
            input_tokens=10,
            output_tokens=32,
        )
        self.assertTrue(recorded)

        row = self.db.query(TokenUsage).one()
        self.assertEqual(row.api_key_id, self.api_key.id)
        self.assertEqual(row.total_tokens, 42)

    def test_get_api_key_token_total_scopes_to_key_and_timeframe(self) -> None:
        now = datetime.now(timezone.utc)
        self.db.add_all(
            [
                TokenUsage(
                    user_id=self.user.id,
                    api_key_id=self.api_key.id,
                    input_tokens=5,
                    output_tokens=5,
                    total_tokens=10,
                    created_at=now - timedelta(minutes=30),
                ),
                TokenUsage(
                    user_id=self.user.id,
                    api_key_id=self.api_key.id,
                    input_tokens=20,
                    output_tokens=20,
                    total_tokens=40,
                    created_at=now - timedelta(hours=2),
                ),
                TokenUsage(
                    user_id=self.user.id,
                    api_key_id=self.other_key_id,
                    input_tokens=100,
                    output_tokens=100,
                    total_tokens=200,
                    created_at=now - timedelta(minutes=10),
                ),
            ]
        )
        self.db.commit()

        self.assertEqual(get_api_key_token_total(self.db, api_key_id=self.api_key.id, timeframe="60m"), 10)
        self.assertEqual(get_api_key_token_total(self.db, api_key_id=self.api_key.id, timeframe="24h"), 50)

    def test_usage_endpoint_returns_total_tokens(self) -> None:
        record_token_usage(
            self.db,
            user_id=self.user.id,
            api_key_id=self.api_key.id,
            total_tokens=123,
            input_tokens=50,
            output_tokens=73,
        )

        response = self.client.get("/v1/usage/24h")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"object": "usage", "timeframe": "24h", "total_tokens": 123},
        )

    def test_usage_endpoint_rejects_invalid_timeframe(self) -> None:
        response = self.client.get("/v1/usage/1y")
        self.assertEqual(response.status_code, 400)

    def test_supported_timeframes(self) -> None:
        self.assertEqual(set(USAGE_TIMEFRAMES), {"60m", "24h", "7d", "30d"})


class RequireApiKeyAccessTests(unittest.TestCase):
    def test_rejects_missing_credentials(self) -> None:
        from app.api.deps import require_api_key_access

        with self.assertRaises(HTTPException) as ctx:
            require_api_key_access(credentials=None, db=MagicMock())
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail, "API key required")


if __name__ == "__main__":
    unittest.main()
