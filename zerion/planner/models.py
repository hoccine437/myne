# planner/models.py
"""
Shared data structures used across the planning engine. Kept dependency-
free (no imports from other planner/ modules) so every other file can
import from here without circular-import risk.
"""

from enum import Enum


class TaskState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class Task:
    """One executable step in a plan. Maps directly onto a single Tool
    Manager call, or (if tool_name is None) onto plain LLM reasoning with
    no tool involved."""

    __slots__ = (
        "id", "description", "tool_name", "parameters", "depends_on",
        "expected_result", "state", "result", "attempts",
    )

    def __init__(self, id: int, description: str, tool_name: str = None,
                 parameters: dict = None, depends_on: list = None,
                 expected_result: str = ""):
        self.id = id
        self.description = description
        self.tool_name = tool_name
        self.parameters = parameters or {}
        self.depends_on = depends_on or []  # list of task ids that must complete first
        self.expected_result = expected_result
        self.state = TaskState.PENDING
        self.result = None  # ToolResult, once executed
        self.attempts = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "depends_on": self.depends_on,
            "expected_result": self.expected_result,
            "state": self.state.value,
        }


class Plan:
    """A goal plus the ordered list of tasks that accomplish it."""

    __slots__ = ("goal", "priority", "tasks", "created_from")

    def __init__(self, goal: str, tasks: list = None, priority: str = "normal",
                 created_from: str = ""):
        self.goal = goal
        self.priority = priority
        self.tasks = tasks or []
        self.created_from = created_from  # the original user request text

    def is_simple(self) -> bool:
        """A plan with zero or one task needs no orchestration overhead —
        the caller can skip straight to executing it."""
        return len(self.tasks) <= 1

    def next_runnable_task(self):
        """Return the next PENDING task whose dependencies have all
        COMPLETED, or None if nothing is runnable right now."""
        completed_ids = {t.id for t in self.tasks if t.state == TaskState.COMPLETED}
        for task in self.tasks:
            if task.state != TaskState.PENDING:
                continue
            if all(dep in completed_ids for dep in task.depends_on):
                return task
        return None

    def is_finished(self) -> bool:
        """True once every task has reached a terminal state."""
        terminal = (TaskState.COMPLETED, TaskState.FAILED, TaskState.SKIPPED, TaskState.CANCELLED)
        return all(t.state in terminal for t in self.tasks)

    def all_succeeded(self) -> bool:
        return all(t.state == TaskState.COMPLETED for t in self.tasks)

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "priority": self.priority,
            "tasks": [t.to_dict() for t in self.tasks],
        }
