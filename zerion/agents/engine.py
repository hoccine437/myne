# agents/engine.py
"""Agent Engine — the formal lifecycle + capability registry over the pool.

The existing AgentPool owns bounds, whitelists and execution; this engine
owns REGISTRATION + LIFECYCLE naming per the target architecture:

    DISCOVERED → REGISTERED → INITIALIZED → READY → RUNNING
    → (PAUSED | FAILED) → STOPPED

Mapping to pool states: pool runs spawn threads; the agent REGISTRATION
exists from the moment the type registers before any work enters. We map,
preserve, and extend — never duplicate the pool.

PLUGIN seam: drop-in agent types at runtime (register_type), the same
"drop a file / register a descriptor" pattern that the tool layer already
has (tools/registry.py) — no main.py edits to add a specialist.
"""

from __future__ import annotations

import threading
import time
import uuid

from agents.service import pool as _pool_singleton  # engine wraps the pool
from agents.types import AGENT_TYPES, AgentType, get_type
from core import events as core_events

AGENT_LIFECYCLE = ("discovered", "registered", "initialized", "ready",
                   "running", "paused", "failed", "stopped")


class AgentHandle:
    __slots__ = ("agent_id", "type", "status", "task", "result",
                 "created_at", "stages")

    def __init__(self, type_name: str, task: dict, stages=None):
        self.agent_id = uuid.uuid4().hex[:10]
        self.type = type_name
        self.status = "ready"
        self.task = task
        self.result = None
        self.created_at = time.time()
        self.stages = []

    def mark(self, state: str):
        self.stages.append((state, time.time()))
        self.status = state


class AgentEngine:
    """The canonical engine. Extends the pool; never replaces it."""

    def __init__(self, pool=None):
        self.pool = pool or _pool_singleton
        self._lock = threading.Lock()
        self._types: dict[str, AgentType] = dict(AGENT_TYPES)

    # -- registry (discovery happens at import: AGENT_TYPES + plugins) ----

    def register_type(self, name: str, description: str,
                      allowed_tools: tuple, can_search_memory: bool = False,
                      max_parallel: int = 2) -> AgentType:
        """Plugin path: register a new specialist type at runtime.
        Registered types retain whitelists — anything they can run flows
        through the same tool manager policy gates."""
        if name in self._types:
            return self._types[name]
        t = AgentType(name=name, description=description,
                      allowed_tools=tuple(allowed_tools),
                      can_search_memory=can_search_memory,
                      max_parallel=max_parallel)
        self._types[name] = t
        AGENT_TYPES[name] = t
        return t

    def list_types(self) -> list:
        rows = []
        for t in self._types.values():
            rows.append({
                "name": t.name, "description": t.description,
                "capabilities": list(t.allowed_tools),
                "memory": t.can_search_memory,
                "max_parallel": t.max_parallel,
                "lifecycle": "registered",
            })
        return rows

    def health(self, name: str = "") -> dict:
        st = self.pool.stats()
        return {"capacity": st["capacity"], "max_pending": st["max_pending"],
                "tracked": st["tracked"], "types": len(self._types),
                "by_type": st["by_type"]}

    # -- the lifecycle contract --------------------------------------------

    def spawn(self, type_name: str, task: dict, wait: bool = True) -> dict:
        h = AgentHandle(type_name, task)
        h.mark("discovered"); h.mark("registered")
        core_events.bus.emit("agent.started", {"type": type_name,
                                               "agent_id": h.agent_id})
        try:
            t = self._types.get(type_name)
            out = self.pool.spawn(t.name if t else type_name, task, wait=wait)
        except Exception as e:
            h.mark("failed")
            core_events.bus.emit("agent.failed", {"type": type_name,
                                                  "error": str(e)[:120]})
            return {"ok": False, "error": "engine_dispatch_failed",
                    "message": str(e), "agent": h.__dict__ if h else None}
        h.mark("running")
        h.result = out
        if isinstance(out, dict) and out.get("agent"):
            agent = out["agent"]
            status = agent.get("status")
            h.mark("failed" if status == "failed" else "stopped")
            core_events.bus.emit(
                "agent.failed" if status == "failed" else "agent.stopped",
                {"type": type_name, "status": status,
                 "agent_id": h.agent_id})
        return {**out, "engine_handle": h.stages}


engine = AgentEngine()
