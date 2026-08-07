# planner/goal.py
"""
Tracks goals across the conversation session. This is in-memory, per-run
state (like main.py's SessionMemory) — it is NOT persisted to disk and is
entirely separate from the long-term memory system in memory/, which the
Planner may read from and write to but never owns.
"""


class GoalManager:
    def __init__(self):
        self.current_goal: str = None
        self.sub_goals: list = []
        self.completed_goals: list = []
        self.failed_goals: list = []
        self.future_goals: list = []

    def set_current(self, goal: str, sub_goals: list = None) -> None:
        self.current_goal = goal
        self.sub_goals = sub_goals or []

    def complete_current(self) -> None:
        if self.current_goal:
            self.completed_goals.append(self.current_goal)
        self.current_goal = None
        self.sub_goals = []

    def fail_current(self, reason: str = "") -> None:
        if self.current_goal:
            self.failed_goals.append({"goal": self.current_goal, "reason": reason})
        self.current_goal = None
        self.sub_goals = []

    def queue_future(self, goal: str) -> None:
        self.future_goals.append(goal)

    def pop_next_future(self):
        return self.future_goals.pop(0) if self.future_goals else None

    def has_active_goal(self) -> bool:
        return self.current_goal is not None

    def summary(self) -> dict:
        return {
            "current_goal": self.current_goal,
            "sub_goals": list(self.sub_goals),
            "completed_count": len(self.completed_goals),
            "failed_count": len(self.failed_goals),
            "queued_count": len(self.future_goals),
        }
