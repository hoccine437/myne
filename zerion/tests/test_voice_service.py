# tests/test_voice_service.py
"""Server-side voice service tests — the Web UI voice path must be the
SAME Core speech implementation as the terminal path, not a disguised
browser fallback. External calls (Gemini HTTP) are mocked; environmental
dependencies (audio players) are mocked explicitly.
"""

import asyncio
import base64
import os
import sys
import tempfile
import unittest
import wave
from unittest import mock

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.chdir(BASE)

import config  # noqa: E402


def _fake_ready(**_): return "Speech: Gemini voice ready."
def _fake_disabled(**_): return "Speech: disabled."


def _write_wav(path, frames=2400, rate=24000):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(rate)
        wf.writeframes(b"\x01\x02" * frames)


class TtsServiceTests(unittest.TestCase):
    def setUp(self):
        from ui.tts import TtsService
        clock = [1000.0]
        self.clock = clock
        self.svc = TtsService(now=lambda: clock[0])
        self.tmp = tempfile.TemporaryDirectory()
        self.seq = 0

    def tearDown(self):
        self.tmp.cleanup()

    def _gen(self, text):
        self.seq += 1
        path = os.path.join(self.tmp.name, f"g{self.seq}.wav")
        _write_wav(path)
        return path

    def req(self, text, seq=None):
        return asyncio.run(self.svc.request(text, seq=seq))

    def _mock_speech(self, ready=True, gen=None):
        # patch.multiple only returns the mocks it created itself — since we
        # pass explicit Mocks, capture them directly for assertions.
        self._gen_mock = mock.Mock(side_effect=gen or (lambda t: self._gen(t)))
        return mock.patch.multiple(
            "speech",
            speech_status=mock.Mock(return_value=_fake_ready() if ready else _fake_disabled()),
            _generate_audio=self._gen_mock,
            _prepare_text=mock.Mock(side_effect=lambda t: t.strip()))

    # --------------------------------------------------------------- shape

    def test_ready_path_returns_gemini_voice_url_and_serves_wav(self):
        with self._mock_speech() as m:
            out = self.req("hello world", seq=42)
        self.assertEqual(out["state"], "ready")
        self.assertEqual(out["voice"], "gemini")
        self.assertEqual(out["seq"], 42)
        self.assertTrue(out["url"].startswith("/api/tts/"))
        entry = self.svc.resolve(out["url"].rsplit("/", 1)[1])
        self.assertIsNotNone(entry)
        self.assertEqual(entry["mime"], "audio/wav")
        with wave.open(entry["path"], "rb") as wf:
            self.assertEqual(wf.getnframes(), 2400)

    def test_deduplication_same_text_one_generation(self):
        with self._mock_speech():
            a = self.req("same text")
            b = self.req("same text")
        self.assertEqual(a["url"], b["url"])
        self.assertTrue(b["cached"])
        self.assertEqual(self._gen_mock.call_count, 1)
        self.assertEqual(self.svc.total_generations, 1)

    def test_rate_limit(self):
        with self._mock_speech():
            results = [self.req(f"hello {i}") for i in range(12)]
            self.assertTrue(all(r["state"] == "ready" for r in results))
            out = self.req("one more")
        self.assertEqual(out["state"], "rate_limited")

    def test_token_expiry(self):
        with self._mock_speech():
            out = self.req("expire me")
        token = out["url"].rsplit("/", 1)[1]
        self.clock[0] += 31 * 60  # past TTL
        self.svc.sweep()
        self.assertIsNone(self.svc.resolve(token))

    def test_unavailable_when_not_configured(self):
        old = config.GEMINI_API_KEY
        config.GEMINI_API_KEY = ""
        try:
            with self._mock_speech(ready=False):
                out = self.req("hi")
        finally:
            config.GEMINI_API_KEY = old
        self.assertEqual(out["state"], "unavailable")

    def test_browser_fallback_is_explicit_when_ready_flickers(self):
        old = config.GEMINI_API_KEY
        config.GEMINI_API_KEY = "present-but-speech-not-ready"
        try:
            with self._mock_speech(ready=False):
                out = self.req("hi")
        finally:
            config.GEMINI_API_KEY = old
        self.assertEqual(out["state"], "browser_fallback")

    def test_empty_and_oversize_text(self):
        with self._mock_speech():
            self.assertEqual(self.req("")["state"], "error")
            self.assertEqual(self.req("x" * 5000)["state"], "error")
            self.assertEqual(self._gen_mock.call_count, 0)

    def test_generation_failure_is_error_state(self):
        with self._mock_speech(gen=lambda t: None):
            out = self.req("will fail")
        self.assertEqual(out["state"], "error")
        self.assertIn("quota", out["reason"])

    def test_no_secret_in_envelope(self):
        with self._mock_speech():
            out = self.req("secrets?")
        import json as _json
        self.assertNotIn(config.GEMINI_API_KEY or "NO_KEY", _json.dumps(out))
        self.assertNotIn("GEMINI_API_KEY".lower(), _json.dumps(out).lower())

    def test_token_never_expands_to_filesystem_path(self):
        """Arbitrary filesystem access must be structurally impossible."""
        self.assertIsNone(self.svc.resolve("/etc/passwd"))
        self.assertIsNone(self.svc.resolve("../../main.py"))
        self.assertIsNone(self.svc.resolve("../"))


# ====================================================================== HTTP

class TtsHttpTests(unittest.TestCase):
    """End-to-end through a LIVE UI server (real uvicorn + real websockets
    + mocked Gemini): WS {type:tts} → tts ready event with /api/tts URL →
    HTTP GET returns the real WAV bytes; unknown tokens 404; no key leaks."""

    def test_live_server_tts_flow(self):
        import socket
        import speech

        # free port
        s = socket.socket(); s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]; s.close()

        from ui.server import app
        import uvicorn

        proc_holder = {}

        def run_server():
            cfg = uvicorn.Config(app, host="127.0.0.1", port=port,
                                 log_level="error", loop="asyncio")
            server = uvicorn.Server(cfg)
            proc_holder["server"] = server
            server.run()

        import threading, time
        import websockets.sync.client as wsc

        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()

        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(speech, "speech_status",
                               return_value="Speech: Gemini voice ready."), \
             mock.patch.object(speech, "_prepare_text",
                               side_effect=lambda t: t.strip()), \
             mock.patch.object(speech, "_generate_audio",
                               side_effect=lambda t: _write_wav(os.path.join(d, "live.wav"))
                               or os.path.join(d, "live.wav")):
            # wait for bind
            import requests as _rq
            url = f"http://127.0.0.1:{port}/health"
            deadline = time.time() + 10
            up = False
            while time.time() < deadline:
                try:
                    if _rq.get(url, timeout=1).ok: up = True; break
                except Exception:
                    time.sleep(0.2)
            self.assertTrue(up, "live UI server did not bind")

            with wsc.connect(f"ws://127.0.0.1:{port}/ws") as ws:
                hello = wsc  # noop to avoid lints
                hello = ws.recv()
                self.assertIn('"hello"', hello)
                ws.send(__import__("json").dumps({"type": "tts", "text": "hello there", "seq": 7}))
                got = None
                for _ in range(600):  # high-ceiling: late-join replay can carry real traffic
                    ev = __import__("json").loads(ws.recv(timeout=10))
                    if ev.get("type") == "tts":
                        got = ev["data"]; break
                self.assertIsNotNone(got, "no tts event on WS")
                self.assertEqual(got["state"], "ready", str(got))

            audio = _rq.get(f"http://127.0.0.1:{port}{got['url']}", timeout=5)
            self.assertEqual(audio.status_code, 200)
            self.assertEqual(audio.headers["content-type"], "audio/wav")
            with wave.open(__import__("io").BytesIO(audio.content), "rb") as wf:
                self.assertEqual(wf.getframerate(), 24000)  # Gemini TTS rate

            # unknown/expired token → 404, never a raw path read
            self.assertEqual(
                _rq.get(f"http://127.0.0.1:{port}/api/tts/../../etc/passwd", timeout=5)
                .status_code in (404, 400), True)

            proc_holder["server"].should_exit = True
            server_thread.join(timeout=8)
            self.assertFalse(server_thread.is_alive())

    def test_error_event_keeps_socket_alive(self):
        """If the TTS request itself fails, the client gets an error event
        and the socket must NOT drop (regression: MAX_TEXT attr crash)."""
        import socket, threading, time
        import websockets.sync.client as wsc
        import json as _json

        s = socket.socket(); s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]; s.close()

        from ui.server import app
        import uvicorn
        proc = {}

        def run_server():
            server = uvicorn.Server(uvicorn.Config(
                app, host="127.0.0.1", port=port, log_level="error", loop="asyncio"))
            proc["server"] = server
            server.run()

        t = threading.Thread(target=run_server, daemon=True)
        t.start()
        import requests as _rq
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                if _rq.get(f"http://127.0.0.1:{port}/health", timeout=1).ok:
                    break
            except Exception:
                time.sleep(0.2)

        with wsc.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            ws.recv()  # hello
            ws.send(_json.dumps({"type": "tts", "text": "hi", "seq": 1}))
            saw = None
            for _ in range(600):  # high-ceiling: late-join replay can carry real traffic
                ev = _json.loads(ws.recv(timeout=10))
                if ev.get("type") == "tts":
                    saw = ev["data"]; break
            self.assertIsNotNone(saw)
            self.assertIn(saw["state"], ("ready", "unavailable",
                                         "browser_fallback", "error"))
            # still alive: ping round-trips after the tts branch
            ws.send(_json.dumps({"type": "ping"}))
            pong = None
            for _ in range(40):
                ev = _json.loads(ws.recv(timeout=10))
                if ev.get("type") == "pong":
                    pong = ev; break
            self.assertIsNotNone(pong, "socket died after a tts error")

        proc["server"].should_exit = True
        t.join(timeout=8)
        self.assertFalse(t.is_alive())


if __name__ == "__main__":
    unittest.main()
