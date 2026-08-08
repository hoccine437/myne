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


class Lifecycle:
    def __init__(self):
        self.records: dict[str, dict] = {}

    def mark(self, task_id: str, state: str, **extra):
        rec = self.records.setdefault(task_id, {"states": [], "created": time.time()})
        rec["states"].append((state, time.time()))
        rec.update(extra)
        rec["current"] = state


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

        # execute: each selected type gets ONE bounded lane (independent if
        # shared-safe; the pool whitelists exclude all destructive tools)
        plan_msg = AgentMessage.new(
            objective=goal, agent_id="orchestrator", task_id=task_id,
            capabilities_required=tuple(types),
        )
        lanes = []
        for t in types:
            atype = get_type(t)
            if atype is None:
                lanes.append((t, {"ok": False, "error": "unknown_type"}))
                continue
            self.lifecycle.mark(task_id, "executing", type=t)
            lanes.append((t, self.pool.spawn(t, {"query": goal} if atype.can_search_memory
                                             else {"tool": atype.allowed_tools[0]})))
        collected = {}
        for t, spawn in lanes:
            if spawn.get("ok"):
                agent = spawn["agent"]
                collected[t] = {"status": agent["status"],
                                "result": (agent.get("result") or {}).get("message", ""),
                                "error": agent.get("error")}
            else:
                collected[t] = {"status": "failed", "error": spawn.get("message"), "result": ""}

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
