# planner/verifier.py
"""
Verifier: checks whether a task's execution actually succeeded and
decides how to proceed after a failure.

Design choice: verification is rule-based (checking ToolResult.success
and basic output sanity), not a separate LLM call per task. Adding an
LLM round-trip after every single tool call would multiply latency and
free-tier rate-limit exposure by the number of tasks in a plan. The
result object from tools/base.py's ToolResult is already a structured
success/error/message/data contract — that's the ground truth this
verifier checks, which is more reliable than asking a free-tier model
to re-judge its own tool's output anyway.
"""

_MAX_CONSECUTIVE_FAILURES_BEFORE_ABORT = 2


def verify_result(result) -> bool:
    """Did this ToolResult actually succeed? Trusts the tool's own
    success flag as ground truth, with one sanity check: a tool that
    claims success but returned no data and no message is suspicious."""
    if result is None:
        return False
    if not result.success:
        return False
    if result.data is None and not result.message:
        return False
    return True


def verify_task(task, plan) -> str:
    """
    Called by the executor after a task has permanently failed (exhausted
    retries). Decides "skip" (continue with the rest of the plan,
    dependents of this task will be cancelled) or "abort" (stop the whole
    plan).

    Rule: abort only if too many tasks in this plan have already failed —
    a single failed step in an otherwise-working plan is worth continuing
    past (e.g. "search X, save notes, summarize" can still summarize what
    it found even if saving to a file failed). Repeated failures suggest
    something structural is wrong (no network, tool consistently broken),
    so abort rather than grinding through every remaining task.
    """
    from planner.models import TaskState
    failed_count = sum(1 for t in plan.tasks if t.state == TaskState.FAILED)
    if failed_count >= _MAX_CONSECUTIVE_FAILURES_BEFORE_ABORT:
        return "abort"
    return "skip"
