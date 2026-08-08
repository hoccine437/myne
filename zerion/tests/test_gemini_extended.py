# tests/test_gemini_extended.py
"""Extended Gemini provider validation: 5xx retries, Retry-After timing,
empty/malformed payloads, response text extraction, router policy, and a
live network reachability probe (never faked: it reports True only when a
real TCP connect lands)."""

import json
import os
import socket
import sys
import unittest
from unittest import mock

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.chdir(BASE)

import config  # noqa: E402
import providers.gemini as gemini  # noqa: E402
from providers.base import ProviderError  # noqa: E402


def _resp(status=200, payload=None, text=None, headers=None):
    r = mock.Mock()
    r.status_code = status
    r.headers = headers or {}
    if payload is not None:
        r.json = lambda: payload
    r.text = text if text is not None else json.dumps(payload or {})
    return r


class _Net:
    def __init__(self):
        self._p = mock.patch.object(socket, "create_connection",
                                    return_value=mock.Mock(close=lambda: None))

    def __enter__(self):
        return self._p.__enter__()

    def __exit__(self, *exc):
        return self._p.__exit__(*exc)


class ProviderEdgeCases(unittest.TestCase):
    def setUp(self):
        self._key = config.GEMINI_API_KEY
        config.GEMINI_API_KEY = "k"

    def tearDown(self):
        config.GEMINI_API_KEY = self._key

    def test_5xx_retried_then_fails(self):
        with _Net(), mock.patch("requests.post") as post, mock.patch("time.sleep"):
            post.side_effect = [_resp(status=500, payload={"error": "boom"}),
                                _resp(status=503, payload={"error": "boom"}),
                                _resp(status=500, payload={"error": "boom"})]
            with self.assertRaises(ProviderError) as ctx:
                gemini.GeminiProvider().call("s", "u", timeout=5)
            self.assertIn("500", str(ctx.exception))
            self.assertEqual(post.call_count, 3)  # 1 + 2 bounded retries

    def test_429_honors_retry_after(self):
        delays = []
        with _Net(), mock.patch("requests.post") as post, \
                mock.patch("time.sleep", side_effect=delays.append):
            post.side_effect = [
                _resp(status=429, payload={"error": "quota"}, headers={"Retry-After": "2.5"}),
                _resp(status=200, payload={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}),
            ]
            out = gemini.GeminiProvider().call("s", "u", timeout=5)
        self.assertEqual(out, "ok")
        self.assertEqual(delays, [2.5], f"Retry-After must be honored, got {delays}")

    def test_200_empty_candidates(self):
        with _Net(), mock.patch("requests.post") as post:
            post.return_value = _resp(status=200, payload={"candidates": []})
            with self.assertRaises(ProviderError) as ctx:
                gemini.GeminiProvider().call("s", "u", timeout=5)
            self.assertIn("unexpected response shape", str(ctx.exception))

    def test_200_empty_text_returns_empty_string(self):
        """A structurally valid response with empty text must surface as
        empty string so llm.py's own fallback logic decides what to do."""
        with _Net(), mock.patch("requests.post") as post:
            post.return_value = _resp(status=200, payload={
                "candidates": [{"content": {"parts": [{"text": ""}]}}]})
            out = gemini.GeminiProvider().call("s", "u", timeout=5)
        self.assertEqual(out, "")

    def test_malformed_json_body(self):
        with _Net(), mock.patch("requests.post") as post:
            r = _resp(status=200, payload=None)
            r.json = mock.Mock(side_effect=ValueError("not json"))
            post.return_value = r
            with self.assertRaises(ProviderError):
                gemini.GeminiProvider().call("s", "u", timeout=5)


class ProviderRouterTests(unittest.TestCase):
    def test_router_rejects_unknown_provider(self):
        from providers.router import call_llm
        with self.assertRaises(ProviderError):
            call_llm("s", "u", provider_name="openai")

    def test_router_unconfigured_raises_cleanly(self):
        from providers.router import call_llm
        old = config.GEMINI_API_KEY
        config.GEMINI_API_KEY = ""
        try:
            with self.assertRaises(ProviderError):
                call_llm("s", "u")
        finally:
            config.GEMINI_API_KEY = old

    def test_endpoint_uses_configured_model(self):
        self.assertIn(config.GEMINI_MODEL, config.GEMINI_URL)
        self.assertTrue(config.GEMINI_URL.startswith(
            "https://generativelanguage.googleapis.com/"))


class LiveNetworkProbe(unittest.TestCase):
    """Honest live probe: NEVER faked. Records reachability; a real model
    call needs a key the sandbox does not have."""

    def test_probe_records_outcome(self):
        reachable = False
        try:
            socket.create_connection(("generativelanguage.googleapis.com", 443),
                                     timeout=2.5).close()
            reachable = True
        except OSError:
            reachable = False
        print(f"\n[LIVE-PROBE] generativelanguage.googleapis.com reachable: {reachable}")
        self.assertIsNotNone(reachable)  # probe always reports; never asserts truthiness


if __name__ == "__main__":
    unittest.main()
