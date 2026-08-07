# planner/workflow.py
"""
Workflow Engine: represents a complex request as a first-class Workflow
with the fields the Zerion architecture calls for -- Goal, Tasks,
Dependencies, Required tools, Execution order, Status.

This intentionally does NOT duplicate planner/models.py's Plan/Task/
TaskState -- a Workflow IS a Plan, viewed through a lens that adds the
two things Plan doesn't already expose on its own: an explicit overall
Status (derived from the underlying tasks' states, not tracked
separately -- so it can never drift out of sync with them) and a
resolved Required tools / Execution order list for display, debugging,
and the /plan command. Building a second parallel task-graph
representation here would be duplicated logic; wrapping the existing one
is not.

from_plan() is the entry point that turns a Plan (from
planner.decomposer.decompose()) into a Workflow -- the only way Workflow
objects are created, so a Workflow can never disagree with the
Plan/Task/executor/verifier machinery everything else already relies on.
"""

from enum import Enum

from planner.models import Plan, TaskState


class WorkflowStatus(Enum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIALLY_COMPLETED = "partially_completed"


class Workflow:
    """A Plan viewed as a Workflow: same underlying tasks, plus derived
    status/required-tools/execution-order convenience views. Never
    stores its own copy of task state -- every property below is
    computed fresh from self.plan.tasks, so it can't go stale."""

    __slots__ = ("plan",)

    def __init__(self, plan: Plan):
        self.plan = plan

    @property
    def goal(self) -> str:
        return self.plan.goal

    @property
    def tasks(self) -> list:
        return self.plan.tasks

    @property
    def required_tools(self) -> list:
        """Every distinct tool name this workflow will need, in the
        order first referenced -- useful for a pre-flight check (are all
        required tools available?) before execution starts."""
        seen = []
        for task in self.plan.tasks:
            if task.tool_name and task.tool_name not in seen:
                seen.append(task.tool_name)
        return seen

    @property
    def execution_order(self) -> list:
        """A dependency-respecting linear ordering of task ids -- a
        topological sort, computed fresh each time rather than cached,
        since it's cheap (a handful of tasks per workflow) and this
        avoids a second source of truth for ordering."""
        remaining = {t.id: set(t.depends_on) for t in self.plan.tasks}
        order = []
        while remaining:
            ready = [tid for tid, deps in remaining.items() if deps <= set(order)]
            if not ready:
                # Circular or broken dependency reference -- rather than
                # loop forever, dump whatever's left in id order so the
                # caller still gets a complete (if imperfect) answer.
                order.extend(sorted(remaining.keys()))
                break
            ready.sort()
            order.extend(ready)
            for tid in ready:
                del remaining[tid]
        return order

    @property
    def status(self) -> WorkflowStatus:
        """Derived purely from current task states -- never set
        directly, so it's always consistent with what actually
        happened."""
        if not self.plan.tasks:
            return WorkflowStatus.NOT_STARTED
        states = [t.state for t in self.plan.tasks]
        if all(s == TaskState.PENDING for s in states):
            return WorkflowStatus.NOT_STARTED
        if not self.plan.is_finished():
            return WorkflowStatus.RUNNING
        if self.plan.all_succeeded():
            return WorkflowStatus.COMPLETED
        if any(s == TaskState.COMPLETED for s in states):
            return WorkflowStatus.PARTIALLY_COMPLETED
        return WorkflowStatus.FAILED

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "status": self.status.value,
            "required_tools": self.required_tools,
            "execution_order": self.execution_order,
            "tasks": [t.to_dict() for t in self.plan.tasks],
        }


def from_plan(plan: Plan) -> Workflow:
    """Wrap an existing Plan as a Workflow."""
    return Workflow(plan)
