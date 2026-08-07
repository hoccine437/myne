# ui/events.py
"""Thread-safe event fan-out between the Core pipeline and web clients.

The Core engines are synchronous and run in worker threads; WebSocket
delivery is asyncio-based. ``EventBus`` bridges both worlds:

* Core/thread side: ``bus.emit(type, payload)`` — never blocks, never
  raises. Events are stamped, seq-numbered, appended to a bounded ring
  buffer (which powers the Logs/DevTools panels and client catch-up),
  and queued for every connected client.
* asyncio side: ``bus.subscribe()`` returns an object with an async
  ``get()`` the socket handler awaits. Subscribe/unsubscribe are async
  because they touch asyncio Queues.

Every event on the wire is ``{"seq": int, "ts": float, "type": str,
"data": {...}}``. The ``data`` shapes are documented in ui/README.md.
"""

from __future__ import annotations

import asyncio
import itertools
import threading
import time
from collections import deque
from typing import Any, Optional


class _Subscription:
    """One client's view of the bus. Holds its own asyncio.Queue; the
    owning loop is recorded so thread-side emits marshal into the right
    loop via call_soon_threadsafe."""

    __slots__ = ("queue", "loop")

    def __init__(self, maxsize: int):
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self.loop: Optional[asyncio.AbstractEventLoop] = None


class EventBus:
    """Process-wide pub/sub with a replay buffer. One instance per app
    (module-level ``bus`` below), mirroring the single-session design of
    the Core's own singletons (tool_manager, planner, action_history)."""

    #: Client-visible event types. Anything outside this set is still
    #: delivered (forward compatibility) — this documents the contract.
    KNOWN_TYPES = {
        "hello",            # initial state dump after connect
        "metrics",          # system telemetry sample (cpu/ram/net/...)
        "agents",           # engine/activity roster update
        "core_state",       # idle|thinking|listening|speaking|searching|
                            # coding|learning|updating|error|success
        "chat",             # {role: user|ai|system, text, kind?}
        "stage",            # pipeline stage begin/end with metadata
        "workspace",        # adaptive workspace mode suggestion
        "focus",            # focus mode on/off + reason
        "tasks",            # planner workflow snapshot (task list)
        "goal",             # current-goal change
        "tool",             # tool execution begin/end
        "decision",         # notable Core decision (critic, planner, policy)
        "notification",     # toast-level message {level, text}
        "confirm_required", # destructive action pending approval
        "turn",             # turn lifecycle (start/end) + latency
        "log",              # mirrored Core log line (core.logging tee)
        "error",            # UI-bridge error surface
        "pong",             # keepalive reply
    }

    def __init__(self, buffer_size: int = 600, queue_size: int = 300):
        self._buffer = deque(maxlen=buffer_size)
        self._subs: list[_Subscription] = []
        self._seq = itertools.count(1)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # producer side (any thread)
    # ------------------------------------------------------------------

    def emit(self, type: str, data: Any = None) -> dict:
        """Record and fan out one event. Safe to call from any thread;
        a slow consumer is dropped-to-latest rather than allowed to block
        the Core pipeline (status telemetry is lossy-tolerant by design,
        but chat/reply events are protected: see _deliver)."""
        event = {
            "seq": next(self._seq),
            "ts": time.time(),
            "type": type,
            "data": data if data is not None else {},
        }
        with self._lock:
            self._buffer.append(event)
            subs = list(self._subs)
        for sub in subs:
            self._deliver(sub, event)
        return event

    @staticmethod
    def _deliver(sub: _Subscription, event: dict) -> None:
        loop = sub.loop
        if loop is None or loop.is_closed():
            return

        def _offer():
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                # Never block the Core on a stalled consumer. Drop only
                # lossy telemetry first; if the queue is still full (a
                # genuinely wedged client) drop the oldest item so the
                # newest state always wins and the stream self-heals.
                try:
                    sub.queue.get_nowait()
                    sub.queue.put_nowait(event)
                except Exception:
                    pass

        try:
            loop.call_soon_threadsafe(_offer)
        except RuntimeError:
            pass  # loop closing mid-emit; safe to ignore

    # ------------------------------------------------------------------
    # consumer side (asyncio)
    # ------------------------------------------------------------------

    async def subscribe(self) -> _Subscription:
        sub = _Subscription(maxsize=300)
        sub.loop = asyncio.get_running_loop()
        with self._lock:
            self._subs.append(sub)
        return sub

    async def unsubscribe(self, sub: _Subscription) -> None:
        with self._lock:
            try:
                self._subs.remove(sub)
            except ValueError:
                pass

    def replay(self, since_seq: int = 0, types: Optional[set] = None) -> list:
        """Buffered events newer than ``since_seq`` (for reconnect
        catch-up and the Logs panel)."""
        with self._lock:
            items = list(self._buffer)
        if types:
            items = [e for e in items if e["type"] in types]
        return [e for e in items if e["seq"] > since_seq]


# Process-wide singleton, like the Core's own tool_manager / action_history.
bus = EventBus()
