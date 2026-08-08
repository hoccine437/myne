# ui/tts.py
"""Server-side voice service for the Web UI — ONE authoritative voice path.

Chain: Zerion response → ui/tts.generate() → Core speech module (Gemini
TTS, the same implementation the terminal path uses) → audio WAV →
/api/tts/<token> → browser <audio> → phone speaker.

Design rules:
- this module owns NO Gemini logic — it delegates to speech.py entirely
  (no second provider, no duplicated API code, no key exposure)
- tokens are unguessable and bound to a message seq; unknown/expired
  tokens are 404 — there is no path traversal surface (serving happens by
  token lookup, never by client-supplied filename)
- generation is deduplicated by content hash: the same text produces one
  file, one API hit — concurrent waits share the same in-flight future
- text length and generation rate are bounded (abuse control)
- the /tts token table expires entries; WAV bytes themselves live in the
  Core's own content-hash cache (speech.py), which exists precisely so
  repeated replies never re-hit the API — we don't keep a second store
- generation runs off the event loop (asyncio.to_thread)
- frontend states are explicit: gemini / generating / browser_fallback /
  unavailable / error — browser TTS is always labeled, never disguised
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
import time

from starlette.concurrency import run_in_threadpool

import config
from core import logging as log

MAX_TEXT = 4000          # chars accepted per request
RATE_LIMIT = 12          # generations per minute (global to the session host)
TOKEN_TTL = 30 * 60      # seconds a /api/tts/<token> URL remains fetchable
INFLIGHT_TTL = 120


class TtsService:
    def __init__(self, *, runtime_dir: str | None = None,
                 now=time.time):
        self.now = now
        self.runtime_dir = runtime_dir
        # token -> {"path": str, "created": float, "seq": int|None, "hash": str}
        self._tokens: dict[str, dict] = {}
        self._hash_to_token: dict[str, str] = {}
        self._inflight: dict[str, asyncio.Future] = {}
        self._rate: list[float] = []
        self.total_generations = 0
        self.total_requests = 0

    # ------------------------------------------------------------------
    # availability
    # ------------------------------------------------------------------

    def availability(self) -> dict:
        """What the UI should show BEFORE the user asks for audio."""
        import speech
        ready = False
        try:
            ready = speech.speech_status() == "Speech: Gemini voice ready."
        except Exception:
            ready = False
        return {
            "gemini_ready": ready,
            "configured": bool(config.GEMINI_API_KEY) and config.gemini_tts_supported(),
        }

    # ------------------------------------------------------------------
    # generation
    # ------------------------------------------------------------------

    async def request(self, text: str, seq: int | None = None,
                      source: str = "chat") -> dict:
        """Front door. Returns a state envelope:
        {state, url?, voice?, reason?, ...}"""
        log.debug(f"tts: request accepted (chars={len(text or '')}, seq={seq}, source={source})")
        self.total_requests += 1
        self.sweep()
        text = (text or "").strip()
        if not text:
            return {"state": "error", "reason": "empty text"}
        if len(text) > MAX_TEXT:
            return {"state": "error", "reason": f"text exceeds {MAX_TEXT} chars"}

        avail = self.availability()
        log.debug(f"tts: availability gemini_ready={avail['gemini_ready']} configured={avail['configured']}")
        if not avail["gemini_ready"]:
            if not avail["configured"]:
                return {"state": "unavailable",
                        "reason": "Gemini voice is not configured on this host"}
            return {"state": "browser_fallback",
                    "reason": "Gemini voice unavailable right now"}

        if not self._rate_ok():
            return {"state": "rate_limited",
                    "reason": f"voice is limited to {RATE_LIMIT} generations/minute"}

        key = self._hash(text)
        token = self._hash_to_token.get(key)
        if token and token in self._tokens and not self._expired(self._tokens[token]):
            if seq is not None:
                self._tokens[token]["seq"] = seq
            return self._ready_envelope(token, key, seq, cached=True)

        # Deduplicate concurrent generations of the same text.
        existing = self._inflight.get(key)
        if existing is not None:
            try:
                token = await existing
            except Exception as e:
                return {"state": "error", "reason": f"generation failed: {e}"}
            if token is None:
                return {"state": "error", "reason": "generation produced no audio"}
            return self._ready_envelope(token, key, seq)

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._inflight[key] = future
        try:
            # starlette-native pool: works under real uvicorn AND the
            # TestClient blocking portal (asyncio.to_thread has a known
            # interaction with anyio-hosted loops in some test harnesses)
            result = await run_in_threadpool(self._generate, text, key, seq)
            future.set_result(result)
        except Exception as e:
            future.set_exception(e)
            self._inflight.pop(key, None)
            return {"state": "error", "reason": f"generation failed: {e}"}
        finally:
            self._inflight.pop(key, None)

        if result is None:
            return {"state": "error",
                    "reason": "Gemini voice produced no audio (quota/network/player)"}
        return self._ready_envelope(result, key, seq)

    def _generate(self, text: str, key: str, seq: int | None) -> str | None:
        """Synchronous worker: reuse the Core speech module end-to-end."""
        import speech

        clean = speech._prepare_text(text)
        if not clean:
            return None
        path = speech._generate_audio(clean)   # the Core's ONLY Gemini TTS
        if not path or not os.path.exists(path):
            return None

        self._rate.append(self.now())
        self.total_generations += 1
        token = secrets.token_urlsafe(18)
        self._tokens[token] = {"path": path, "created": self.now(),
                               "seq": seq, "hash": key}
        self._hash_to_token[key] = token
        return token

    def _ready_envelope(self, token: str, key: str, seq: int | None,
                        cached: bool = False) -> dict:
        return {"state": "ready", "voice": "gemini", "cached": cached,
                "url": f"/api/tts/{token}", "seq": seq,
                "hash": key[:12]}

    # ------------------------------------------------------------------
    # serving & lifecycle
    # ------------------------------------------------------------------

    def resolve(self, token: str) -> dict | None:
        """Token → {path, mime}. Never resolves client paths."""
        entry = self._tokens.get((token or "").strip())
        if not entry or self._expired(entry):
            return None
        if not os.path.isfile(entry["path"]):
            return None
        return {"path": entry["path"], "mtime": entry["created"],
                "mime": "audio/wav", "seq": entry["seq"]}

    def sweep(self) -> int:
        """Expire tokens/WAV references past TTL; cancels stale inflight."""
        cutoff = self.now() - TOKEN_TTL
        dead = [t for t, e in self._tokens.items() if e["created"] < cutoff]
        for t in dead:
            e = self._tokens.pop(t)
            self._hash_to_token.pop(e["hash"], None)
        # rate window bookkeeping lives on the same sweep
        self._rate = [t for t in self._rate if self.now() - t < 60.0]
        return len(dead)

    def stats(self) -> dict:
        return {"tokens": len(self._tokens), "inflight": len(self._inflight),
                "generated": self.total_generations, "requests": self.total_requests,
                **self.availability()}

    # ------------------------------------------------------------------

    def _hash(self, text: str) -> str:
        return hashlib.sha256(
            f"{text}|{config.VOICE_NAME}|{config.GEMINI_TTS_MODEL}".encode()
        ).hexdigest()

    def _rate_ok(self) -> bool:
        cutoff = self.now() - 60.0
        self._rate = [t for t in self._rate if t >= cutoff]
        return len(self._rate) < RATE_LIMIT

    def _expired(self, entry: dict) -> bool:
        return self.now() - entry["created"] > TOKEN_TTL


service = TtsService()
