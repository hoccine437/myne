# phone/audit.py
"""Append-only phone action audit trail.

Every PhoneAction transition is a JSON line in
runtime/run/phone_audit.jsonl (gitignored runtime state). Bounded at
~1MB with a single-rotate policy. This file is the only authoritative
record of physical-body effects; constitutional integrity for content
still lives upstream in the Constitution/policy layer."""

from __future__ import annotations

import json
import os
import threading


class PhoneAuditLog:
    def __init__(self, path: str, max_bytes: int = 1_000_000):
        self.path = path
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)

    def record(self, event: dict) -> None:
        line = json.dumps({"ts": time_safe(), **event}, ensure_ascii=False)
        with self._lock:
            try:
                if os.path.exists(self.path) and os.path.getsize(self.path) > self.max_bytes:
                    try:
                        os.replace(self.path, self.path + ".1")
                    except OSError:
                        pass
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass

    def tail(self, limit: int = 50) -> list:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except Exception:
            return []
        out = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out


def time_safe() -> float:
    import time
    return round(time.time(), 3)
