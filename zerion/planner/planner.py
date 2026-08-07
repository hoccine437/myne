# planner/planner.py
"""
Top-level Planner: the single entry point main.py talks to. Wires
together the Context Manager, Task Decomposer, Execution Engine, Verifier,
and Goal Manager without main.py needing to know about any of them
individually.

Request flow implemented here:

    user_text -> build_context() -> decompose() -> [simple?] -> caller falls
                                                  -> [complex?] -> execute_plan()
                                                                 -> verify per task
                                                                 -> resume on confirm
                                                                 -> summary back to caller

For a SIMPLE request, `handle_request()` returns None — this tells
main.py "nothing to do here, proceed with the normal llm.get_llm_output()
single-turn path exactly as before." This keeps the common case (a plain
question, or a request needing at most one tool) exactly as fast and
simple as it was before the planner existed; the multi-step machinery
only engages when the decomposer actually finds a multi-step task.
"""

from planner.context import build_context
from planner.decomposer import decompose
from planner.executor import execute_plan, resume_after_confirmation, ExecutionPaused
from planner.goal import GoalManager
from planner.state import PlannerState
from planner.workflow import from_plan
from core import logging as log

goal_manager = GoalManager()
planner_state = PlannerState()

DEBUG = False  # toggle via set_debug(); disabled by default per spec


def set_debug(enabled: bool) -> None:
    global DEBUG
    DEBUG = enabled


def _debug_log(plan) -> None:
    """Emit optional planner diagnostics through the common logger."""
    if not DEBUG:
        return
    workflow = from_plan(plan)
    log.debug(f"planner goal={workflow.goal!r} status={workflow.status.value} "
              f"tools={workflow.required_tools} order={workflow.execution_order}")
    for task in plan.tasks:
        log.debug(f"planner task={task.id} state={task.state.value} "
                  f"tool={task.tool_name!r} description={task.description!r}")


def current_workflow():
    """Return a Workflow view of the currently active (possibly paused)
    plan, or None if nothing is active. Used by intent.commands' /plan
    to show workflow-shaped status instead of raw task dicts."""
    if planner_state.active_plan is None:
        return None
    return from_plan(planner_state.active_plan)


def has_paused_plan() -> bool:
    return planner_state.has_active_plan()


def resume_paused_plan(confirmed_result) -> dict:
    """Called by main.py when the user confirms a destructive task that
    paused a multi-step plan. Resumes execution from where it stopped."""
    plan = planner_state.active_plan
    if plan is None:
        return {"goal": "", "all_succeeded": False, "aborted": True, "tasks": []}

    try:
        summary = resume_after_confirmation(plan, confirmed_result, debug=DEBUG)
    except ExecutionPaused:
        # Another destructive task later in the same plan also needs
        # confirmation — stay paused, caller will prompt again.
        _debug_log(plan)
        return {"paused": True, "goal": plan.goal}

    _debug_log(plan)
    planner_state.clear_active()
    if summary["all_succeeded"]:
        goal_manager.complete_current()
    else:
        goal_manager.fail_current(reason="one or more tasks failed")
    return summary


def cancel_paused_plan() -> None:
    planner_state.clear_active()
    goal_manager.fail_current(reason="cancelled by user")


def handle_request(user_text: str, minimal_memory: dict, recent_history: str):
    """
    Entry point for a new user turn. Returns:
      - None, if the request is simple (caller should use the normal
        single-turn llm.get_llm_output() path — no planning needed)
      - a dict summary, if the request was complex and a plan was
        executed (successfully, partially, or aborted)
      - raises nothing: on any internal error, falls back to returning
        None so the caller degrades to normal chat rather than breaking
    """
    try:
        context = build_context(user_text, minimal_memory, recent_history,
                                 current_goal=goal_manager.current_goal)
        plan = decompose(context.user_text, context.available_tools)
    except Exception as e:
        log.warning(f"planner context/decompose failed; falling back to normal chat: {e}")
        return None

    if plan.is_simple():
        return None  # let main.py's existing single-turn path handle it

    goal_manager.set_current(plan.goal, sub_goals=[t.description for t in plan.tasks])
    planner_state.set_active(plan)

    try:
        summary = execute_plan(plan, debug=DEBUG)
    except ExecutionPaused as e:
        _debug_log(plan)
        return {
            "paused": True,
            "goal": plan.goal,
            "confirmation_message": e.tool_result.message,
        }
    except Exception as ex:
        log.error(f"planner execution failed unexpectedly: {ex}")
        planner_state.clear_active()
        goal_manager.fail_current(reason=str(ex))
        return {"goal": plan.goal, "all_succeeded": False, "aborted": True, "tasks": [],
                "error": str(ex)}

    _debug_log(plan)
    planner_state.clear_active()
    if summary["all_succeeded"]:
        goal_manager.complete_current()
    else:
        goal_manager.fail_current(reason="one or more tasks failed")
    return summary
