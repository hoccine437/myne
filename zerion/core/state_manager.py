# core/state_manager.py
"""State Manager — the clean interface between agents/turns and persistent
state, per PHASE 6 (MEMORY ≠ STATE ≠ CONTEXT).

   STATE    — what is currently running/pending right now.
              session (SessionMemory), planner state, pool occupancy,
              approval slots, autopilot overview, service state.

This module reads the existing singletons — it delegates, never duplicates.
That matters: session state already lives in intent/session_state.py,
planner state in planner/state.py, agent state in the pool, comm state in
comms/store+overrides. One owner per concern; this layer ASSEMBLES views.

State transitions (writes) that matter to consumers:
  - cancel_pending(): single safe path: planner cancel + tool confirm cancel
    + (tool manager has nothing pending) → consistent abort signal
  - note/queue states are read in by snapshot()
"""

from __future__ import annotations


class StateManager:
    """Assembly-only; reads come from the owners, not copies."""

    def snapshot(self) -> dict:
        """Machine state for the System panel + readiness audits."""
        out = {"session": {}, "planner": {}, "agents": {}, "comm": {}}
        try:
            from planner import planner as pp
            out["planner"] = {
                "active_workflow": bool(getattr(pp, "current_workflow", lambda: None)()),
                "goals": pp.goal_manager.summary(),
            }
        except Exception:
            pass
        try:
            from agents.engine import engine as agent_engine
            h = agent_engine.health()
            out["agents"] = {"capacity": h["capacity"], "tracked": h["tracked"],
                             "types": h["types"], "by_type": h["by_type"],
                             "lifecycle": "registered"}
        except Exception:
            pass
        try:
            from comms import overrides, store
            store.init_all()
            out["comm"] = {"paused": overrides.is_paused(),
                           "estop": overrides.is_estopped(),
                           "pending_drafts": len(store.pending_drafts())}
        except Exception:
            pass
        return out

    def cancel_pending(self) -> dict:
        """One stop gesture: cancel tool confirmations + paused plans + any
        pending phone approvals UI-side. Returns what really changed."""
        from planner import planner as pp
        from tools.manager import tool_manager
        changed = {"planner": False, "tool": False}
        if pp.has_paused_plan():
            pp.cancel_paused_plan()
            changed["planner"] = True
        if tool_manager.has_pending_confirmation():
            tool_manager.cancel_pending_confirmation()
            changed["tool"] = True
        return changed


state_manager = StateManager()
