# planner/state.py
"""
Tracks the currently active Plan across turns, in memory only — this is
session state, not persisted long-term memory. Needed because a plan can
pause mid-execution (a destructive task awaiting confirmation) and must
resume on the user's next input rather than being lost.
"""


class PlannerState:
    def __init__(self):
        self.active_plan = None  # the Plan currently executing/paused, or None

    def set_active(self, plan) -> None:
        self.active_plan = plan

    def clear_active(self) -> None:
        self.active_plan = None

    def has_active_plan(self) -> bool:
        return self.active_plan is not None
