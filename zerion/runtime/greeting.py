# runtime/greeting.py
"""Startup greeting — once per startup, after READY, voice-first.

Contract (per product spec):
* fires only after Core initialization + health checks have succeeded
  (callers deliver it from the READY transition, never earlier)
* uses the existing voice/output system (``speech.speak``) when voice is
  available; plain text through the provided text channel otherwise
* short and natural; the wording is a configuration value
  (``ZERION_GREETING``), not a scripted speech — ``{name}`` is filled
  from the existing user profile in long-term memory
  (memory.identity.name.value), and only when it already exists;
  nothing is invented
* guarded against double-delivery per startup
* non-blocking: voice synthesis/network runs on a short-lived daemon
  thread, while service startup proceeds immediately

The greeting goes through the Core's own speech module, so caching,
TTS capability checks and graceful fallbacks are inherited — this module
contains no TTS or audio logic of its own.
"""

from __future__ import annotations

import threading

import speech
from runtime import rcfg

_greeted = False
_guard = threading.Lock()


def voice_available() -> bool:
    """True when the Core's speech stack reports itself ready."""
    try:
        return speech.speech_status() == "Speech: Gemini voice ready."
    except Exception:
        return False


def build_greeting(memory: dict | None = None, template: str | None = None) -> str:
    """Compose the greeting text. `{name}` resolves to the stored user
    name with a leading comma-space (", Nadia") when the profile already
    knows it, and to the empty string otherwise."""
    template = (template if template is not None else rcfg.GREETING_TEMPLATE)
    name = ""
    try:
        if memory:
            value = (memory.get("identity", {}).get("name") or {}).get("value")
            if isinstance(value, str) and value.strip():
                name = f", {value.strip()}"
    except Exception:
        name = ""
    text = template.replace("{name}", name)
    return " ".join(text.split())  # collapse any spacing artifacts


def deliver_startup_greeting(*, memory: dict | None = None,
                             text_channel=None,
                             blocking: bool = False,
                             template: str | None = None) -> str | None:
    """Deliver the greeting once. Returns the greeting text (None when
    skipped: disabled or already delivered this startup).

    ``text_channel`` is the text fallback sink (e.g. TerminalUI.write_log,
    print, or a UI chat emitter). Voice goes first when available; text is
    the fallback in exact accordance with the availability rules.
    """
    global _greeted
    if not rcfg.GREETING_ENABLED:
        return None
    with _guard:
        if _greeted:
            return None
        _greeted = True

    text = build_greeting(memory=memory, template=template)
    channel = text_channel or (lambda t: print(t, flush=True))

    if voice_available():
        if blocking:
            _speak(text)
        else:
            # short-lived daemon: never blocks the READY transition or the
            # main loop; dies with the process like every other worker here
            threading.Thread(target=_speak, args=(text,),
                             name="zerion-greeting", daemon=True).start()
    else:
        try:
            channel(text)
        except Exception:
            pass
    return text


def _speak(text: str) -> None:
    try:
        speech.speak(text)
    except Exception:
        pass  # speech can never crash startup


def reset_for_tests() -> None:
    """Test hook — production callers must deliver once per process."""
    global _greeted
    with _guard:
        _greeted = False
