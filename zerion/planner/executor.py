# planner/executor.py
"""
Execution Engine: runs a Plan's tasks in dependency order, one at a time,
through the existing Tool Manager (tools/manager.py) — this module never
calls a tool directly, per the constraint that the planner must not
bypass the Tool Manager.

Failure policy per task (kept simple and predictable, not configurable
per-task, to keep this lightweight):
  - A tool that returns confirmation_required pauses the whole plan and
    surfaces the confirmation prompt to the caller (main.py), same as a
    single-tool call would. The plan resumes from that task once
    confirmed.
  - A tool that fails for any other reason is retried once. If it fails
    again, the task is marked FAILED and the executor asks the Verifier
    whether to skip-and-continue or abort the remaining plan.
  - A step with no tool_name (pure reasoning) is marked COMPLETED
    immediately without calling anything — the Planner's caller handles
    surfacing reasoning-only steps via the normal LLM response.
"""

from planner.models import TaskState
from planner.verifier import verify_task
from tools.manager import tool_manager


class ExecutionPaused(Exception):
    """Raised to signal the plan is paused waiting on a destructive-tool
    confirmation. Carries the task that needs confirmation."""
    def __init__(self, task, tool_result):
        self.task = task
        self.tool_result = tool_result
        super().__init__(f"Execution paused: '{task.tool_name}' needs confirmation.")


def execute_plan(plan, debug: bool = False) -> dict:
    """
    Run every runnable task in `plan` until the plan is finished, a task
    needs confirmation (raises ExecutionPaused), or the Verifier decides
    to abort. Returns a summary dict — never raises except
    ExecutionPaused, which main.py is expected to catch and handle the
    same way it already handles a single destructive-tool confirmation.
    """
    aborted = False

    while not plan.is_finished() and not aborted:
        task = plan.next_runnable_task()
        if task is None:
            # Nothing runnable but plan isn't finished — a dependency
            # chain is broken (e.g. its dependency failed). Cancel the
            # rest rather than looping forever.
            for t in plan.tasks:
                if t.state == TaskState.PENDING:
                    t.state = TaskState.CANCELLED
            break

        if debug:
            print(f"[planner] running task {task.id}: {task.description}")

        task.state = TaskState.RUNNING
        task.attempts += 1

        if task.tool_name is None:
            # Reasoning-only step — nothing to execute; the caller's LLM
            # response covers this narratively. Mark it done so the plan
            # can proceed.
            task.state = TaskState.COMPLETED
            continue

        result = tool_manager.execute(task.tool_name, task.parameters)

        if result.error == "confirmation_required":
            task.state = TaskState.PENDING  # will be re-run after confirmation
            task.attempts -= 1
            raise ExecutionPaused(task, result)

        task.result = result

        if result.success:
            task.state = TaskState.COMPLETED
            if debug:
                print(f"[planner] task {task.id} completed: {result.message[:80]}")
            continue

        # Failure path
        if task.attempts < 2:
            task.state = TaskState.PENDING  # retry once
            if debug:
                print(f"[planner] task {task.id} failed, retrying: {result.message[:80]}")
            continue

        task.state = TaskState.FAILED
        if debug:
            print(f"[planner] task {task.id} failed permanently: {result.message[:80]}")

        decision = verify_task(task, plan)
        if decision == "abort":
            aborted = True
            for t in plan.tasks:
                if t.state == TaskState.PENDING:
                    t.state = TaskState.CANCELLED
        # "skip" (the only other outcome) just continues the loop —
        # the failed task stays FAILED and next_runnable_task() moves on
        # to whatever doesn't depend on it.

    return {
        "goal": plan.goal,
        "all_succeeded": plan.all_succeeded(),
        "aborted": aborted,
        "tasks": [t.to_dict() for t in plan.tasks],
    }


def resume_after_confirmation(plan, confirmed_result, debug: bool = False) -> dict:
    """
    Called by main.py after the user confirms (or the tool executes)
    a paused destructive task. Applies the result to the matching
    PENDING task and resumes execution.
    """
    task = plan.next_runnable_task()
    if task is not None:
        task.result = confirmed_result
        task.state = TaskState.COMPLETED if confirmed_result.success else TaskState.FAILED
        if not confirmed_result.success:
            decision = verify_task(task, plan)
            if decision == "abort":
                for t in plan.tasks:
                    if t.state == TaskState.PENDING:
                        t.state = TaskState.CANCELLED
                return {
                    "goal": plan.goal, "all_succeeded": False, "aborted": True,
                    "tasks": [t.to_dict() for t in plan.tasks],
                }

    return execute_plan(plan, debug=debug)
