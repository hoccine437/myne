# comms/health.py
"""Background communication health snapshot (mission §6).

autopilot.pump() writes runtime/run/comm_health.json on every cycle with:
service state, listener/connector map, queue depth, workflow counts,
last_event / last_action / last_error with ages. Readers: the 24/7 service
probe, /api/comm/overview, and the comm_health tool. The file reflects real
runtime facts only; an absent file means "autopilot has not run yet" (never
fabricated as healthy).
"""

from __future__ import annotations

import json
import os
import time


def _path() -> str:
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "runtime", "run")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "comm_health.json")


_last_event_at = 0.0
_last_action_at = 0.0
_last_error = ""


def note_event() -> None:
    global _last_event_at
    _last_event_at = time.time()


def note_action() -> None:
    global _last_action_at
    _last_action_at = time.time()


def note_error(text: str) -> None:
    global _last_error
    _last_error = str(text)[:200]


def write(service_state: str, queue_depth: int, workflows_active: int = 0) -> dict:
    from comms.registry import connectors
    snap = {
        "service": service_state,            # active | degraded | idle | disabled
        "connectors": connectors.health(),
        "queue_pending": queue_depth,
        "workflows_active": workflows_active,
        "last_event_age_s": (round(time.time() - _last_event_at, 1)
                             if _last_event_at else None),
        "last_action_age_s": (round(time.time() - _last_action_at, 1)
                              if _last_action_at else None),
        "last_error": _last_error or None,
        "written_at": round(time.time(), 1),
    }
    try:
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(snap, f)
    except Exception:
        pass
    return snap


def read() -> dict:
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"service": "not-running-yet"}
