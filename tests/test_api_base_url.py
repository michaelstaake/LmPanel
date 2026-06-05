from __future__ import annotations

import unittest

from app.utils.schemas import build_api_base_url


class BuildApiBaseUrlTests(unittest.TestCase):
    def test_appends_frontend_port_when_public_url_has_no_port(self) -> None:
        self.assertEqual(
            build_api_base_url("https://lmpanel.example.com", "https://localhost:8443"),
            "https://lmpanel.example.com:8443",
        )

    def test_returns_empty_when_public_url_missing(self) -> None:
        self.assertEqual(build_api_base_url("", "https://localhost:8443"), "")

    def test_keeps_public_url_without_port_on_standard_https_origin(self) -> None:
        self.assertEqual(
            build_api_base_url("https://lmpanel.example.com", "https://lmpanel.example.com"),
            "https://lmpanel.example.com",
        )


if __name__ == "__main__":
    unittest.main()
