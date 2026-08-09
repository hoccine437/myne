# core/workflow_orchestrator.py
"""Workflow Orchestrator — owns the ROUTE decision of one conversational turn.

    Request (normalized by the caller)
      → classify   (intent.engine — zero-LLM rules)
      → capability fast-lane  (fast planner / meta / command palette)
      → complexity          → planner  (config.planner_active)
      → specialist evidence   → agents (agents/orchestrator.py — consult)
      → else: the LLM turn continues at Cognitive Reasoning layer

This module does NOT re-implement the pipeline; it is the named owner of the
routing boundary so the brain isn't "main.py + inline branches scattered
across ui/session". Both front ends call intent.engine.process() which
delegates here; the orchestrator is where every routing decision is named,
observable and test-covered.
"""

from __future__ import annotations

from agents.orchestrator import orchestrator as _agent_orchestrator
from core import events as core_events


def consult_agents(user_text: str, classification, memory: dict):
    """The specialist consult that used to live inside intent/engine.py —
    moved here wholesale so routing ownership is named ONCE. Behavior gates
    unchanged (they are evidence gates, not policy)."""
    import config
    from intent.models import Intent

    if not config.ORCHESTRATION_ENABLED:
        return None
    if classification is None or classification.intent is not Intent.CHAT:
        return None

    from agents.orchestrator import classify as orch_classify
    types, _reason = orch_classify(user_text)
    if len(types) < 2:
        return None

    core_events.bus.emit("plan.started",
                         {"kind": "agent_orchestration", "goal": user_text[:120]})
    result = _agent_orchestrator.run(user_text)
    core_events.bus.emit(
        "plan.completed" if result.get("orchestrated") else "plan.paused",
        {"kind": "agent_orchestration", "orchestrated": result.get("orchestrated")})
    if not result.get("orchestrated"):
        return None

    # evidence gates stay exactly where the contract was: substantive-only,
    # coverage-gated, critic-accept before answering in place of the model
    from intent.engine import _NO_EVIDENCE, _evidence_on_topic
    lanes = result.get("lanes") or {}
    meaningful = [t for t, c in lanes.items()
                  if (c.get("result") or "").strip()
                  and _NO_EVIDENCE not in str(c.get("result"))]
    if not meaningful:
        return None
    aggregate = result.get("aggregate", "")
    if not _evidence_on_topic(user_text, aggregate):
        return None
    verdict = (result.get("critic") or {}).get("verdict")
    if verdict != "accept":
        try:
            memory["orchestrated_evidence"] = (
                f"unverified specialist-lane findings (confidence "
                f"{result.get('confidence')}):\n{aggregate[:800]}")
        except Exception:
            pass
        return None

    headline = (f"[orchestrated: {', '.join(result.get('agents', []))} — "
                f"critic accepted, confidence {result.get('confidence')}]")
    return {
        "text": f"{headline}\n{aggregate[:1200]}",
        "handled_by": "orchestrator",
        "tool_used": "agent_orchestrate",
        "orchestration": {
            "task_id": result.get("task_id"),
            "agents": result.get("agents"),
            "verdict": verdict,
            "confidence": result.get("confidence"),
            "finished_ms": result.get("finished_ms"),
        },
    }
