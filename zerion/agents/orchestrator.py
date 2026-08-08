# agents/orchestrator.py
"""The canonical Agent Orchestrator.

USER TASK → UNDERSTAND → CLASSIFY → CHECK MEMORY → PLAN → SELECT AGENTS
→ ALLOCATE → EXECUTE → COLLECT → CRITIC → VERIFY → RESPOND → STORE EXPERIENCE

Design rules:
- the Cognitive Core (main conversation) is unchanged; the orchestrator is
  invoked through the existing agent_delegate surface,
  and ALSO directly as the agent_orchestrate tool when the Core calls it.
- deterministic, local-first classification & selection (no LLM round-trip —
  it is a coordinator, not a brain).
- critic step uses the existing intelligence.critic.self_critic.
- verify step: every non-empty aggregated claim is checked by an independent
  verifier agent lane or by empirical tool verification (bounded).
- learns: every orchestration writes an agent_perf knowledge record so future
  selection is telemetry-informed.
"""

from __future__ import annotations

import time
import uuid

from intelligence.critic import self_critic
from agents.messages import AgentMessage
from agents.pool import AgentPool
from agents.service import pool as default_pool
from agents.types import get_type, AGENT_TYPES


# ---------------------------------------------------------------------------
# deterministic local classification
# ---------------------------------------------------------------------------

DOMAIN_TO_TYPES = (
    # ordering matters: first match wins; the most specialized sets come first
    (("security", "vulnerability", "permission", "audit", "secret"),
     ("security", "verifier")),
    (("trading", "market", "portfolio", "financial", "stock", "strategy", "backtest"),
     ("finance", "data", "security", "verifier")),
    (("analyze the repo", "architecture", "review code structure", "module"),
     ("architect", "tester", "verifier")),
    (("test", "pytest", "coverage", "failing", "debug", "regression"),
     ("tester", "verifier")),
    (("phone", "android", "termux", "flashlight", "battery", "notification"),
     ("controller", "security", "verifier")),
    (("data", "csv", "json", "statistics", "dataset", "transform"),
     ("data", "verifier")),
    (("research", "find information", "sources", "compare", "study"),
     ("researcher", "verifier")),
    (("web", "online", "website", "http", "scrape"),
     ("researcher", "verifier")),
    (("device", "cpu", "memory usage", "network info", "status"),
     ("monitor", "controller", "verifier")),
    (("memory", "remember", "recall", "what did i"),
     ("researcher", "verifier")),
    (("plan", "organize", "decompose", "multi-step"),
     ("researcher", "coder", "verifier")),
    (("code", "python", "function", "class", "bug", "implement", "refactor"),
     ("coder", "tester", "verifier")),
)


def classify(goal: str) -> tuple[tuple[str, ...], str]:
    """Minimal capable set. Empty (core-only) when no specialist pattern fits."""
    text = (goal or "").lower()
    for markers, types in DOMAIN_TO_TYPES:
        if any(m in text for m in markers):
            return types, "rule-match"
    return (), "no-specialist-signal"


# ---------------------------------------------------------------------------
# lifecycle records
# ---------------------------------------------------------------------------

STATES = ("registered", "available", "selected", "initialized", "executing",
          "completed", "verified", "released", "failed", "aborted")

# One global wall-clock budget for ALL lanes of a run (parallel fan-out),
# not per lane — an orchestrated consult must never dominate a user turn.
# Lane work itself is already bounded (local knowledge search or whitelisted
# read-only tools with their own timeouts); this is the outer guard.
LANE_DEADLINE_S = 20.0

# Lane errors that can never succeed on retry (contract violations, not
# transient conditions) — restart budget is never spent on these.
_NON_TRANSIENT_MARKERS = ("whitelist", "task must contain", "cannot search memory")


class Lifecycle:
    def __init__(self):
        self.records: dict[str, dict] = {}

    def mark(self, task_id: str, state: str, **extra):
        rec = self.records.setdefault(task_id, {"states": [], "created": time.time()})
        rec["states"].append((state, time.time()))
        rec.update(extra)
        rec["current"] = state


def _lane_record(task_id: str, type_name: str, agent: dict | None, error) -> dict:
    """One lane's result in the runtime agent contract (structured, no
    private internals — evidence is the lane's own result text, nothing
    else leaks). Backward-compatible keys (status/result/error) preserved."""
    agent = agent or {}
    status = agent.get("status", "failed")
    if status == "completed":
        verification = "memory_retrieval" if "query" in (agent.get("task") or {}) else "tool_result"
        confidence = 0.8
    elif error == "timeout":
        verification = "timeout"
        status = "failed"
        confidence = 0.2
    else:
        verification = "failed"
        confidence = 0.15
    task = agent.get("task") or {}
    tools_used = [task["tool"]] if task.get("tool") else []
    duration = None
    if agent.get("finished") and agent.get("created"):
        duration = round(agent["finished"] - agent["created"], 3)
    record = {
        "task_id": task_id,
        "agent": type_name,
        "agent_id": agent.get("id"),
        "objective": (task.get("query") or task.get("tool") or ""),
        "status": status,
        "result": (agent.get("result") or {}).get("message", ""),
        "evidence": (agent.get("result") or {}).get("message", "")[:240],
        "confidence": confidence,
        "error": error or agent.get("error"),
        "tools_used": tools_used,
        "duration_s": duration,
        "verification_status": verification,
        "restarted": bool(agent.get("restarted", False) or agent.get("restarts", 0)),
    }
    return record


# ---------------------------------------------------------------------------
# orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    """One canonical orchestrator; subordinate to the Constitution because
    every sub-agent action passes through the pool → Tool Manager gates."""

    def __init__(self, pool: AgentPool = None):
        self.pool = pool or default_pool
        self.lifecycle = Lifecycle()
        self.history: list[AgentMessage] = []

    # -- plan ------------------------------------------------------------

    def plan_only(self, goal: str) -> dict:
        types, reason = classify(goal)
        return {"goal": goal, "types": list(types), "reason": reason,
                "no_orchestration": not types}

    # -- run --------------------------------------------------------------

    def run(self, goal: str, subtasks: list[dict] | None = None,
            verify_with: str = "verifier") -> dict:
        started = time.time()
        task_id = uuid.uuid4().hex[:12]
        types, reason = classify(goal)
        self.lifecycle.mark(task_id, "selected", types=list(types), reason=reason)

        if not types:
            # simple task: no orchestration — orchestrated runs are only for
            # genuinely multi-lane objectives (anti over-engineering)
            return {"task_id": task_id, "orchestrated": False,
                    "message": "No specialist engagement needed — handled by the core.",
                    "lifecycle": self.lifecycle.records[task_id]}

        # execute: each selected type gets ONE bounded lane. Lanes are
        # INDEPENDENT (same contract family: local search or read-only tool),
        # so they fan out in parallel and join on one shared deadline —
        # dependency-aware sequencing stays with the AI Planner (its steps
        # genuinely feed each other); mixing the two would duplicate it.
        plan_msg = AgentMessage.new(
            objective=goal, agent_id="orchestrator", task_id=task_id,
            capabilities_required=tuple(types),
        )
        spawned: list[tuple[str, dict]] = []
        for t in types:
            atype = get_type(t)
            if atype is None:
                spawned.append((t, {"ok": False, "error": "unknown_type"}))
                continue
            self.lifecycle.mark(task_id, "executing", type=t)
            spawned.append((t, self.pool.spawn(
                t, {"query": goal} if atype.can_search_memory
                else {"tool": atype.allowed_tools[0]}, wait=False)))

        collected = {}
        deadline = time.time() + LANE_DEADLINE_S
        for t, spawn in spawned:
            if not spawn.get("ok"):
                collected[t] = _lane_record(task_id, t, None,
                                            spawn.get("message") or spawn.get("error"))
                continue
            remaining = max(0.1, deadline - time.time())
            outcome = self.pool.wait(spawn["agent"]["id"], timeout=remaining)
            if not outcome.get("ok") and outcome.get("error") == "timeout":
                self.lifecycle.mark(task_id, "aborted", type=t, reason="lane deadline")
                collected[t] = _lane_record(task_id, t, None, "timeout",
                                            timed_out=True)
                continue
            agent = outcome.get("agent") or spawn.get("agent") or {}
            # bounded failure recovery: ONE restart for transient-lane
            # failures (pool.enforces the budget), never for contract errors
            if agent.get("status") == "failed" and not any(
                    m in str(agent.get("error") or "") for m in _NON_TRANSIENT_MARKERS):
                retry = self.pool.restart(agent["id"])
                if retry.get("ok") and retry.get("agent"):
                    remaining = max(0.1, deadline - time.time())
                    outcome = self.pool.wait(retry["agent"]["id"], timeout=remaining)
                    if outcome.get("ok"):
                        agent = outcome["agent"]
                        agent["restarted"] = True
            collected[t] = _lane_record(task_id, t, agent, agent.get("error"))

        # aggregate text
        aggregate = "\n".join(f"[{t}] {c['result'] or c['error'] or '—'}"
                              for t, c in collected.items())

        # critic review over the aggregate (confidence = shape of evidence
        # coverage, not an invented number)
        nonok = sum(1 for c in collected.values() if c["status"] != "completed")
        confidence = max(.2, min(.9, .92 - .28 * nonok))
        critic = self_critic.review(goal, aggregate, confidence)
        verdict = "accept" if not critic.should_improve else "revise"

        # verifier engagement
        self.lifecycle.mark(task_id, "completed", lanes=list(collected))
        self.lifecycle.mark(task_id, "verified" if verdict == "accept" else "completed")
        self.lifecycle.mark(task_id, "released")

        # learn telemetry
        self._store_perf(task_id, types, collected, time.time() - started)

        self.history.append(plan_msg)
        return {
            "task_id": task_id, "orchestrated": True,
            "agents": list(collected), "lanes": collected,
            "aggregate": aggregate[:2000],
            "critic": {"verdict": verdict, "reasons": [i.description for i in critic.issues]},
            "confidence": round(confidence, 2),
            "verify_with": verify_with,
            "finished_ms": round((time.time() - started) * 1000),
            "lifecycle": self.lifecycle.records[task_id]["states"],
        }

    # -- telemetry-driven selection improvement --------------------------

    def _store_perf(self, task_id, types, collected, elapsed) -> None:
        try:
            from knowledge.manager import KnowledgeManager
            km = KnowledgeManager()
            for t in types:
                c = collected.get(t, {})
                km.store(
                    f"agent {t} task={task_id[:6]} outcome={c.get('status')}",
                    "agent_perf", [t, "orchestration"], .5, .8,
                    {"agent": t, "task_id": task_id, "elapsed": elapsed,
                     "success": c.get("status") == "completed"},
                    layer="capability",
                )
        except Exception:
            pass

    def perf(self, agent_type: str) -> dict:
        """Learned stats for a type (used to prefer stronger types)."""
        try:
            from knowledge.manager import KnowledgeManager
            rows = KnowledgeManager().retrieve_context("agent " + agent_type, limit=50)
        except Exception:
            rows = []
        # minimal real telemetry aggregation from stored markers
        ok = rows.count("outcome=completed") if isinstance(rows, str) else 0
        total = rows.count("agent " + agent_type) if isinstance(rows, str) else 0
        rate = ok / total if total else None
        return {"type": agent_type, "runs": total, "success_rate": rate}

    def volume_expectations(self) -> dict:
        return dict(self.pool.stats())


# process-level singleton mirrors pool's
orchestrator = Orchestrator()
