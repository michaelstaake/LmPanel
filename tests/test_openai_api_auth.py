"""Tests for OpenAI-compatible API auth split between models and chat."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import openai_compat
from app.core import config


def _openai_test_client() -> TestClient:
    app = FastAPI()
    app.include_router(openai_compat.router)
    return TestClient(app)


class OpenAIApiAuthTests(unittest.TestCase):
    def tearDown(self) -> None:
        config.get_settings.cache_clear()

    def test_models_public_chat_requires_auth_by_default(self) -> None:
        env = {
            "OPENAI_API_AUTH_REQUIRED": "true",
            "OPENAI_MODELS_AUTH_REQUIRED": "false",
        }
        with patch.dict(os.environ, env, clear=False):
            config.get_settings.cache_clear()
            client = _openai_test_client()

            models_response = client.get("/v1/models")
            self.assertEqual(models_response.status_code, 200)
            self.assertEqual(models_response.json().get("object"), "list")

            chat_response = client.post(
                "/v1/chat/completions",
                json={"model": "test", "messages": [{"role": "user", "content": "hi"}]},
            )
            self.assertEqual(chat_response.status_code, 401)

    def test_models_requires_auth_when_enabled(self) -> None:
        env = {
            "OPENAI_API_AUTH_REQUIRED": "true",
            "OPENAI_MODELS_AUTH_REQUIRED": "true",
        }
        with patch.dict(os.environ, env, clear=False):
            config.get_settings.cache_clear()
            client = _openai_test_client()

            response = client.get("/v1/models")
            self.assertEqual(response.status_code, 401)
