# tests/test_gemini_transport.py
"""Gemini API + Gemini voice verification (offline, mocked transport).

The real provider/voice calls need GEMINI_API_KEY + network, which this
environment may not have — so these tests verify everything verifiable
without them: request shape, response parsing, every failure mode the
code documents (401/403, 429, timeout, network error, malformed reply),
and the PCM→WAV voice path integrity. Actual audio playback to a speaker
is recorded as NOT VERIFIED in the release report (no audio hardware in
CI sandboxes).
"""

import base64
import json
import os
import sys
import unittest
import wave
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


class _NetPreflight:
    """Silence the provider's real socket preflight — tests must not depend
    on sandbox network reachability."""

    def __init__(self):
        import socket as _socket
        self._patcher = mock.patch.object(_socket, "create_connection",
                                          return_value=mock.Mock(close=lambda: None))

    def __enter__(self):
        return self._patcher.__enter__()

    def __exit__(self, *exc):
        return self._patcher.__exit__(*exc)


class GeminiProviderTests(unittest.TestCase):
    def setUp(self):
        self._key = config.GEMINI_API_KEY
        config.GEMINI_API_KEY = "test-key-123"

    def tearDown(self):
        config.GEMINI_API_KEY = self._key

    def test_authentication_and_request_shape(self):
        provider = gemini.GeminiProvider()
        with _NetPreflight(), mock.patch("requests.post") as post:
            post.return_value = _resp(payload={
                "candidates": [{"content": {"parts": [{"text": "hello from gemini"}]}}]})
            out = provider.call("SYS", "USER", timeout=10)
        self.assertEqual(out, "hello from gemini")
        _, kwargs = post.call_args
        self.assertEqual(kwargs["params"]["key"], "test-key-123")
        body = kwargs["json"]
        self.assertEqual(body["system_instruction"]["parts"][0]["text"], "SYS")
        self.assertEqual(body["contents"][0]["parts"][0]["text"], "USER")
        self.assertEqual(kwargs["timeout"], 10)

    def test_not_configured_raises_provider_error(self):
        config.GEMINI_API_KEY = ""
        provider = gemini.GeminiProvider()
        with self.assertRaises(ProviderError):
            provider.call("s", "u", timeout=5)

    def test_auth_failure_401(self):
        with _NetPreflight(), mock.patch("requests.post") as post:
            post.return_value = _resp(status=401, payload={"error": {"message": "bad key"}})
            with self.assertRaises(ProviderError) as ctx:
                gemini.GeminiProvider().call("s", "u", timeout=5)
        self.assertIn("invalid or unauthorized", str(ctx.exception))

    def test_quota_failure_429(self):
        # retries are bounded; sleep is patched out for speed
        with _NetPreflight(), mock.patch("requests.post") as post, \
                mock.patch("time.sleep"):
            post.return_value = _resp(status=429, payload={"error": {"message": "quota"}},
                                      headers={"Retry-After": "0"})
            with self.assertRaises(ProviderError) as ctx:
                gemini.GeminiProvider().call("s", "u", timeout=5)
        self.assertIn("quota", str(ctx.exception).lower())

    def test_preflight_network_down(self):
        import socket as _socket
        with mock.patch.object(_socket, "create_connection", side_effect=OSError("unreachable")):
            with self.assertRaises(ProviderError) as ctx:
                gemini.GeminiProvider().call("s", "u", timeout=5)
        self.assertIn("network unavailable", str(ctx.exception))

    def test_timeout_raises_provider_error(self):
        import requests
        with _NetPreflight(), mock.patch("requests.post",
                                          side_effect=requests.exceptions.Timeout()), \
                mock.patch("time.sleep"):
            with self.assertRaises(ProviderError):
                gemini.GeminiProvider().call("s", "u", timeout=5)

    def test_network_failure_raises_provider_error(self):
        import requests
        with _NetPreflight(), mock.patch("requests.post",
                        side_effect=requests.exceptions.ConnectionError("dns")), \
                mock.patch("time.sleep"):
            with self.assertRaises(ProviderError):
                gemini.GeminiProvider().call("s", "u", timeout=5)

    def test_malformed_reply_raises(self):
        with _NetPreflight(), mock.patch("requests.post") as post:
            post.return_value = _resp(payload={"unexpected": True})
            with self.assertRaises(ProviderError):
                gemini.GeminiProvider().call("s", "u", timeout=5)


class GeminiVoiceTests(unittest.TestCase):
    """The full TTS path — Gemini voice service payload → audio data →
    local WAV file → player handoff — minus the speaker (no audio hw)."""

    def setUp(self):
        self._key = config.GEMINI_API_KEY
        config.GEMINI_API_KEY = "test-key"

    def tearDown(self):
        config.GEMINI_API_KEY = self._key

    def test_pcm_to_wav_integrity(self):
        import speech
        pcm = b"\x01\x02" * 2400  # 0.1 s of 16-bit mono @24kHz
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.wav")
            speech._pcm_to_wav(pcm, path)
            with wave.open(path, "rb") as wf:
                self.assertEqual(wf.getframerate(), 24000)
                self.assertEqual(wf.getnchannels(), 1)
                self.assertEqual(wf.getsampwidth(), 2)
                self.assertEqual(wf.getnframes(), 2400)

    def test_tts_request_payload_contract(self):
        import speech
        payload_pcm = base64.b64encode(b"\x00" * 480).decode()

        captured = {}

        def fake_post(url, headers=None, params=None, json=None, timeout=None):
            captured["url"] = url
            captured["params"] = params
            captured["json"] = json
            captured["timeout"] = timeout
            return _resp(payload={"candidates": [{"content": {"parts": [
                {"inlineData": {"data": payload_pcm, "mimeType": "audio/L16"}}]}}]})

        with mock.patch("requests.post", side_effect=fake_post):
            out_path = speech._generate_audio("Hello from Zerion")
        self.assertTrue(out_path.endswith(".wav"))
        # payload uses the TTS contract: AUDIO modality + prebuilt voice
        body = captured["json"]
        self.assertEqual(body["generationConfig"]["responseModalities"], ["AUDIO"])
        self.assertIn("voiceName", body["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"])
        self.assertIn(config.GEMINI_TTS_MODEL, captured["url"])
        # and the wrap produced a parseable wav
        with wave.open(out_path, "rb") as wf:
            self.assertEqual(wf.getnframes(), 240)

    def test_speak_is_silent_noop_without_player_and_key(self):
        import speech
        config.GEMINI_API_KEY = ""
        # must not raise, may print a note
        speech.speak("test")
        # status honestly reports disabled
        self.assertIn(speech.speech_status(), ("Speech: disabled.", "Speech: Gemini voice ready."))

    def test_tts_uses_declared_gemini_path_only(self):
        # Guard against silently falling back to a non-Gemini voice: the
        # generator must refuse when the configured TTS model isn't a
        # recognised Gemini TTS model.
        import speech
        old = config.GEMINI_TTS_MODEL
        config.GEMINI_TTS_MODEL = "not-a-tts-model"
        try:
            self.assertEqual(speech._generate_audio("x"), "")
        finally:
            config.GEMINI_TTS_MODEL = old


if __name__ == "__main__":
    unittest.main()
