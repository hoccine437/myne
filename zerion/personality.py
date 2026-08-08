# personality.py
"""Persona modes for Zerion: NORMAL (default) and SERIOUS.

The mode switch (via the command palette — 'START SERIOUS MODE' or
'/serious') is not a label. It changes behavior through the existing
prompt channel: cognition/engine.prepare() appends persona rules into
reasoning_rules, which main.py places into the model's context block
verbatim. zerion's identity, constitutional law and protected boundaries
are entirely unaffected — rules here are style/directness constraints
only, and explicitly carry "boundaries still apply" into the prompt.

State persists in long-term memory (preferences.personality.value), so a
restart keeps the user's chosen mode. Thread-safe, migration-safe: a
missing/foreign value simply falls back to NORMAL.
"""

from __future__ import annotations

import threading

NORMAL = "normal"
SERIOUS = "serious"

MODES = (NORMAL, SERIOUS)

_PERSONA_RULES = {
    NORMAL: (),
    SERIOUS: (
        "Persona: serious mode is active — answer directly and task-first.",
        "Skip pleasantries, filler and hedging that adds no information.",
        "Default to actionable, checkable output.",
        "Security, safety, Constitution and system-integrity boundaries remain fully active.",
    ),
}

_ack = {
    NORMAL: "Normal mode active. Balanced conversational assistance restored.",
    SERIOUS: "Serious mode active — direct, task-focused responses. All safety and system boundaries remain on.",
}

_lock = threading.Lock()
_current: str | None = None  # lazily loaded from memory on first access


def _load() -> str:
    global _current
    if _current is not None:
        return _current
    try:
        from memory.memory_manager import load_memory
        value = (load_memory().get("preferences", {}).get("personality", {}) or {}).get("value")
        _current = value if value in MODES else NORMAL
    except Exception:
        _current = NORMAL
    return _current


def current() -> str:
    with _lock:
        return _load()


def set_mode(mode: str) -> str:
    """Switch mode; persists via the memory manager. Returns the ACK text."""
    global _current
    mode = (mode or "").strip().lower()
    if mode not in MODES:
        raise ValueError(f"unknown personality mode {mode!r}")
    with _lock:
        _current = mode
    try:
        from memory.memory_manager import update_memory
        update_memory({"preferences": {"personality": {"value": mode}}})
    except Exception:
        pass  # persistence failure never breaks the switch
    return _ack[mode]


def serious_active() -> bool:
    """True while Serious Mode is engaged. Used by policy gates (strictest
    discipline wins when combined with communication workflows)."""
    return current() == SERIOUS


def persona_rules() -> tuple:
    return _PERSONA_RULES.get(current(), ())


def ack_for(mode: str) -> str:
    return _ack.get(mode, "")
