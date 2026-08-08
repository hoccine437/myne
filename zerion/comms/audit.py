# comms/audit.py
"""Append-only audit trail for every EXTERNAL communication action.

Fields per the accountability contract: timestamp, platform, account,
action, target, workflow, agent, permission level, result, error,
verification. Secrets never enter this file: the writer redacts any
key that smells like a credential, and callers pass action metadata only.

Path: runtime/run/comm_audit.jsonl (gitignored runtime dir, same family as
the phone audit trail).
"""

from __future__ import annotations

import json
import os
import time

_SECRET_WORDS = ("password", "token", "secret", "api_key", "apikey",
                 "authorization", "credential", "otp", "pin")


def _path() -> str:
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "runtime", "run")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "comm_audit.jsonl")


def _clean(value):
    if isinstance(value, dict):
        return {k: ("[redacted]" if any(w in k.lower() for w in _SECRET_WORDS)
                    else _clean(v)) for k, v in value.items()}
    if isinstance(value, str) and len(value) > 600:
        return value[:600] + "…"
    return value


def record(action: str, platform: str, account: str = "", target: str = "",
           workflow: str = "", agent: str = "", permission_level: int | None = None,
           result: str = "", error: str = "", verification: str = "",
           extra: dict | None = None) -> None:
    entry = {
        "ts": round(time.time(), 3),
        "action": action, "platform": platform, "account": account,
        "target": target, "workflow": workflow, "agent": agent,
        "permission_level": permission_level,
        "result": str(result)[:200], "error": str(error)[:200],
        "verification": verification,
    }
    if extra:
        entry["extra"] = _clean(extra)
    try:
        with open(_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(_clean(entry)) + "\n")
    except Exception:
        pass  # audit must never break the action path (but every caller logs too)


def tail(limit: int = 50) -> list:
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception:
        return []
    out = []
    for line in lines[-int(limit):]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out
