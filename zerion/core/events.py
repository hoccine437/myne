# core/events.py
"""Internal typed event bus — decoupling layer for subsystem telemetry
(mission PHASE 9). In-process, in-memory, replayable; NOT replaceable
with ui.events (that's the WebSocket fan-out for clients).

Wiring discipline: events appear ONLY where a second consumer legitimately
exists. Direct calls stay direct — this is not an "everything is an event"
refactor.

Emission sites today:
  tool_manager.execute()       → tool.called / tool.failed
  agents/engine.py lifecycle   → agent.started / agent.stopped / agent.failed
  planner handle_request       → plan.started / plan.completed / plan.paused
  runtime HealthMonitor        → health.degraded / health.recovered
  comms.engine send            → comm.sent / comm.rejected (mirrors audit)

Subscribers:
  ui/server.py lifespan hooks the feed into the browser event bus
  consumers (see ui/server.py); tests can tap the ring buffer directly.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

KNOWN_TYPES = {
    "tool.called", "tool.failed",
    "agent.started", "agent.stopped", "agent.failed",
    "plan.started", "plan.completed", "plan.paused",
    "health.degraded", "health.recovered",
    "comm.sent", "comm.rejected",
    "evolution.started", "evolution.completed",
}


@dataclass(frozen=True)
class CoreEvent:
    type: str
    payload: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


class InternalBus:
    def __init__(self, buffer_size: int = 400):
        self._buffer = []
        self._subs = []
        self._lock = threading.Lock()
        self._size = buffer_size

    def emit(self, type: str, payload: dict | None = None) -> CoreEvent:
        ev = CoreEvent(type=type, payload=payload or {})
        with self._lock:
            self._buffer.append(ev)
            if len(self._buffer) > self._size:
                self._buffer.pop(0)
            subs = list(self._subs)
        for fn in subs:
            try:
                fn(ev)
            except Exception:
                pass  # observers never break emitters
        return ev

    def subscribe(self, fn) -> None:
        with self._lock:
            self._subs.append(fn)

    def unsubscribe(self, fn) -> None:
        with self._lock:
            if fn in self._subs:
                self._subs.remove(fn)

    def replay(self, since_ts: float = 0.0) -> list:
        with self._lock:
            return [e for e in self._buffer if e.ts > since_ts]

    def clear(self) -> None:
        with self._lock:
            self._buffer = []


bus = InternalBus()
