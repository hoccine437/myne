# intent/session_state.py
"""
Session State: a single read-only view over state that already exists in
main.py's SessionMemory, planner.planner's GoalManager/PlannerState, and
tools.manager's ToolManager. This module does NOT hold its own copy of
that state -- duplicating it would contradict "avoid duplicated logic"
and create two sources of truth that could drift apart. It exists so
main.py's /status command (and anything else that wants a full picture)
has one function to call instead of reaching into four different
modules' internals.

Background jobs: no background-task system exists yet (see main
README/planner README for why -- deferred as a distinct follow-up), so
that field is always an empty list for now. The field is included so the
shape is stable once background tasks are added later.
"""


def snapshot(session, tool_manager, planning_engine, action_history) -> dict:
    """Assemble a point-in-time view of everything session-related."""
    goal_summary = planning_engine.goal_manager.summary()

    return {
        "current_goal": goal_summary["current_goal"],
        "sub_goals": goal_summary["sub_goals"],
        "completed_goals": goal_summary["completed_count"],
        "failed_goals": goal_summary["failed_count"],
        "queued_goals": goal_summary["queued_count"],
        "current_task": session.pending_intent,
        "pending_tool_confirmation": tool_manager.has_pending_confirmation(),
        "pending_plan_confirmation": planning_engine.has_paused_plan(),
        "background_jobs": [],  # reserved for future background-task system
        "recent_actions": action_history.recent(limit=5),
        "action_totals": action_history.summary(),
    }
