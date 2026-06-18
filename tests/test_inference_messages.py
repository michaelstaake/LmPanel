"""Tests for chat message sanitization before inference."""

from __future__ import annotations

import unittest

from app.utils.schemas import message_content_is_empty, sanitize_inference_messages


class InferenceMessageSanitizationTests(unittest.TestCase):
    def test_drops_assistant_without_content_or_tool_calls(self) -> None:
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": ""},
            {"role": "user", "content": "follow up"},
        ]
        sanitized = sanitize_inference_messages(messages)
        self.assertEqual(
            sanitized,
            [
                {"role": "user", "content": "hello"},
                {"role": "user", "content": "follow up"},
            ],
        )

    def test_keeps_assistant_with_tool_calls_and_empty_content(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "web_search", "arguments": "{}"}}],
            }
        ]
        sanitized = sanitize_inference_messages(messages)
        self.assertEqual(len(sanitized), 1)
        self.assertEqual(sanitized[0]["role"], "assistant")
        self.assertNotIn("content", sanitized[0])
        self.assertIn("tool_calls", sanitized[0])

    def test_strips_empty_content_from_user_messages(self) -> None:
        messages = [{"role": "user", "content": ""}, {"role": "user", "content": "hi"}]
        sanitized = sanitize_inference_messages(messages)
        self.assertEqual(sanitized, [{"role": "user", "content": "hi"}])

    def test_message_content_is_empty_for_multimodal_without_text(self) -> None:
        self.assertTrue(message_content_is_empty([]))
        self.assertFalse(
            message_content_is_empty(
                [{"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}]
            )
        )


if __name__ == "__main__":
    unittest.main()
