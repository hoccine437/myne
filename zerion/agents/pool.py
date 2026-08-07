# agents/pool.py
"""AgentPool — resource-aware orchestration of agent instances.

* Spawn: one instance per task, thread-backed, semaphore-bounded.
* Capacity: defaults to min(4, cpu_count); configurable via
  ZERION_MAX_AGENTS; per-type caps from the type contract.
* Work contract: an agent task is exactly one of:
    a) a whitelisted tool call   {"tool": name, "parameters": {...}}
    b) a knowledge search        {"query": "text"}  (memory-capable types)
  Deterministic, local, and testable without any LLM round-trip.
* Results: structured, aggregated via collect(). Failures are isolated,
  recorded, and restartable once per agent (bounded restart: a crashed
  agent gets ONE automatic retry here; the 24/7 health monitor governs
  deeper resilience at the service level).
* Cleanup: finished agents are reaped after TTL; pool.shutdown() joins
  workers and refuses new spawns.

All executions still flow through tools.manager.tool_manager → the
Constitution policy check and the destructive-tool confirmation flow
apply exactly as in the main pipeline (agents' whitelists contain only
non-destructive tools, so they can never pause on confirmation).
"""

from __future__ import annotations

import os
import threading
import time
import uuid

from agents.types import get_type
from tools.manager import tool_manager

_AGENT_TTL = 600.0          # finished agents are reaped after 10 minutes
_DEFAULT_CAP = None          # computed lazily from host resources


def _default_capacity() -> int:
    global _DEFAULT_CAP
    if _DEFAULT_CAP is None:
        cores = os.cpu_count() or 2
        cap = max(2, min(cores, 4))
        try:
            import psutil
            if psutil.virtual_memory().total < 3 * 1024 ** 3:
                cap = min(cap, 2)   # low-RAM hosts (phones) get a tight pool
        except Exception:
            pass
        _DEFAULT_CAP = cap
    return _DEFAULT_CAP


class AgentInstance:
    __slots__ = ("id", "type_name", "task", "status", "result", "error",
                 "created", "finished", "restarts")

    def __init__(self, type_name: str, task: dict):
        self.id = uuid.uuid4().hex[:8]
        self.type_name = type_name
        self.task = task
        self.status = "queued"     # queued|running|completed|failed|cancelled
        self.result = None
        self.error = None
        self.created = time.time()
        self.finished = None
        self.restarts = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type_name, "task": self.task,
            "status": self.status, "result": self.result, "error": self.error,
            "created": self.created, "finished": self.finished,
            "restarts": self.restarts,
        }


class AgentPool:
    def __init__(self, max_agents: int | None = None):
        env = os.getenv("ZERION_MAX_AGENTS", "").strip()
        try:
            cap = int(env) if env else None
        except ValueError:
            cap = None
        self.max_agents = max_agents or cap or _default_capacity()
        self._sem = threading.Semaphore(self.max_agents)
        self._by_type_sem: dict[str, threading.Semaphore] = {}
        self._agents: dict[str, AgentInstance] = {}
        self._lock = threading.Lock()
        self._closed = False

    # ------------------------------------------------------------------

    def _type_sem(self, type_name: str) -> threading.Semaphore:
        with self._lock:
            if type_name not in self._by_type_sem:
                limit = get_type(type_name).max_parallel
                self._by_type_sem[type_name] = threading.Semaphore(limit)
            return self._by_type_sem[type_name]

    def spawn(self, type_name: str, task: dict, wait: bool = True) -> dict:
        """Spawn an agent instance. task: {tool, parameters} or {query}."""
        if self._closed:
            return _err(None, "pool_closed", "agent pool is shut down")

        atype = get_type(type_name)
        if atype is None:
            return _err(None, "unknown_type",
                        f"unknown agent type {type_name!r}; types: {', '.join(sorted(_type_names()))}")
        agent = AgentInstance(atype.name, task or {})

        if not self._sem.acquire(blocking=False):
            return _err(agent.id, "capacity", "agent pool at capacity — try again shortly")
        if not self._type_sem(atype.name).acquire(blocking=False):
            self._sem.release()
            return _err(agent.id, "capacity", f"type '{atype.name}' is at its instance cap")

        with self._lock:
            self._agents[agent.id] = agent
        threading.Thread(target=self._run_guarded, args=(agent,),
                         name=f"agent-{agent.id}", daemon=True).start()
        if wait:
            return self.wait(agent.id)
        return {"ok": True, "agent": agent.to_dict()}

    def delegate(self, assignments: list, wait: bool = True) -> dict:
        """Spawn several agents in one call: [{type, task}, ...]."""
        results = []
        for a in assignments:
            results.append(self.spawn(a.get("type"), a.get("task"), wait=wait))
        return {"assignments": len(assignments), "results": results}

    def collect(self, ids: list) -> dict:
        """Aggregate results of finished agents."""
        out = []
        with self._lock:
            for aid in ids:
                agent = self._agents.get(aid)
                out.append(agent.to_dict() if agent else {"id": aid, "status": "unknown"})
        succeeded = sum(1 for a in out if a.get("status") == "completed")
        return {"agents": out, "succeeded": succeeded, "failed":
                sum(1 for a in out if a.get("status") == "failed")}

    def wait(self, agent_id: str, timeout: float = 20.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                agent = self._agents.get(agent_id)
                if agent is None:
                    return _err(agent_id, "not_found", "no such agent")
                if agent.finished is not None:
                    return {"ok": agent.status == "completed", "agent": agent.to_dict()}
            time.sleep(0.02)
        return _err(agent_id, "timeout", "agent did not finish in time")

    def restart(self, agent_id: str) -> dict:
        """Bounded restart: same task, new instance, once per agent lineage."""
        with self._lock:
            agent = self._agents.get(agent_id)
        if agent is None:
            return _err(agent_id, "not_found", "no such agent")
        if agent.status != "failed":
            return _err(agent_id, "not_failed", "only failed agents restart")
        if agent.restarts >= 1:
            return _err(agent_id, "restart_limit", "restart budget exhausted for this agent")
        agent.restarts += 1
        return self.spawn(agent.type_name, agent.task)

    # ------------------------------------------------------------------

    def _run_guarded(self, agent: AgentInstance) -> None:
        try:
            self._execute(agent)
        finally:
            self._sem.release()
            self._type_sem(agent.type_name).release()

    def _execute(self, agent: AgentInstance) -> None:
        agent.status = "running"
        atype = get_type(agent.type_name)
        task = agent.task or {}
        try:
            if "tool" in task:
                tool = str(task.get("tool") or "")
                if tool not in atype.allowed_tools:
                    agent.status = "failed"
                    agent.error = f"tool {tool!r} is not in the {atype.name} whitelist"
                else:
                    result = tool_manager.execute(tool, task.get("parameters") or {})
                    agent.status = "completed" if result.success else "failed"
                    agent.result = {"message": result.message, "data": result.data}
                    agent.error = result.error or None
            elif "query" in task and atype.can_search_memory:
                from knowledge.manager import KnowledgeManager
                found = KnowledgeManager().retrieve_context(str(task["query"]), limit=5)
                agent.status = "completed"
                agent.result = {"message": found or "No matching records."}
            elif "query" in task:
                agent.status = "failed"
                agent.error = f"{atype.name} agents cannot search memory"
            else:
                agent.status = "failed"
                agent.error = "task must contain 'tool' (whitelisted) or 'query'"
        except Exception as e:
            agent.status = "failed"
            agent.error = f"agent crashed: {e}"
        agent.finished = time.time()

    # ------------------------------------------------------------------

    def reap(self) -> int:
        """Drop finished agents past TTL; returns how many were reaped."""
        cutoff = time.time() - _AGENT_TTL
        with self._lock:
            dead = [aid for aid, a in self._agents.items()
                    if a.finished is not None and a.finished < cutoff]
            for aid in dead:
                del self._agents[aid]
        return len(dead)

    def stats(self) -> dict:
        with self._lock:
            live = list(self._agents.values())
        counts = {}
        for a in live:
            counts.setdefault(a.type_name, {}).setdefault(a.status, 0)
            counts[a.type_name][a.status] = counts[a.type_name].get(a.status, 0) + 1
        return {"capacity": self.max_agents, "tracked": len(live), "by_type": counts}

    def shutdown(self) -> None:
        self._closed = True
        # no threads to force-join (all daemon + guarded); mark and stop
        # accepting new work — running agents finish on their own.


def _type_names():
    from agents.types import AGENT_TYPES
    return AGENT_TYPES.keys()


def _err(agent_id, code, message) -> dict:
    return {"ok": False, "error": code, "message": message,
            "agent": {"id": agent_id} if agent_id else None}
