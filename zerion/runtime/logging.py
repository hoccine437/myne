# runtime/logging.py
"""Structured logging for the long-lived runtime.

Two channels, one call:

* a JSON-lines log file (default ``runtime/run/service.log.jsonl``) with
  size-based rotation — machine-readable, suited to log inspection, the
  UI Logs panel, and service managers;
* the Core's own ``core.logging`` console logger, mirrored for WARNING
  and above so interactive runs stay human-readable.

The record shape is stable: ``{ts, level, event, component, message,
data?}`` — ``data`` holds arbitrary JSON-serializable context.
"""

from __future__ import annotations

import json
import os
import threading
import time

from core import logging as console


class StructuredLogger:
    """Bounded JSONL writer. Thread-safe; all I/O failures are swallowed
    (logging must never be able to crash the service)."""

    def __init__(self, path: str, max_bytes: int = 1_000_000, backups: int = 2,
                 echo_level: str = "WARNING"):
        self.path = path
        self.max_bytes = max_bytes
        self.backups = backups
        self.echo_level = echo_level
        self._lock = threading.Lock()
        self.records = 0
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)

    # -- public ------------------------------------------------------------

    def log(self, level: str, event: str, component: str, message: str,
            data: dict | None = None) -> dict:
        record = {
            "ts": round(time.time(), 3),
            "level": level.upper(),
            "event": event,
            "component": component,
            "message": message,
        }
        if data:
            try:
                json.dumps(data)
                record["data"] = data
            except (TypeError, ValueError):
                record["data"] = {"repr": repr(data)[:500]}
        with self._lock:
            self.records += 1
            self._write(record)
        if record["level"] in ("WARNING", "ERROR", "CRITICAL") or self.echo_level == "DEBUG":
            line = f"[{record['component']}] {record['message']}"
            (console.error if record["level"] in ("ERROR", "CRITICAL")
             else console.warning if record["level"] == "WARNING"
             else console.info)(line)
        return record

    def debug(self, event, component, message, data=None):
        return self.log("DEBUG", event, component, message, data)

    def info(self, event, component, message, data=None):
        return self.log("INFO", event, component, message, data)

    def warning(self, event, component, message, data=None):
        return self.log("WARNING", event, component, message, data)

    def error(self, event, component, message, data=None):
        return self.log("ERROR", event, component, message, data)

    def critical(self, event, component, message, data=None):
        return self.log("CRITICAL", event, component, message, data)

    # -- internals -----------------------------------------------------------

    def _write(self, record: dict) -> None:
        try:
            line = json.dumps(record, ensure_ascii=False) + "\n"
            if os.path.exists(self.path) and os.path.getsize(self.path) > self.max_bytes:
                self._rotate()
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass

    def _rotate(self) -> None:
        try:
            for i in range(self.backups, 0, -1):
                src = f"{self.path}.{i}"
                dst = f"{self.path}.{i + 1}"
                if os.path.exists(src):
                    if i == self.backups:
                        os.remove(src)
                    else:
                        os.replace(src, dst)
            os.replace(self.path, f"{self.path}.1")
        except Exception:
            pass
