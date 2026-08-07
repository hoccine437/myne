# intent/history.py
"""
Action History: an in-memory log of what was executed this session --
tool name, duration, success/failure, and reason on failure. Session-only
(not persisted to disk), same as planner/goal.py and planner/state.py --
this is operational telemetry, not long-term memory, and deliberately
stays out of memory/memory.json.
"""

import time


class ActionHistory:
    def __init__(self, max_entries: int = 200):
        self.max_entries = max_entries
        self._entries = []

    def record(self, tool_name: str, success: bool, duration_seconds: float,
               reason: str = "") -> None:
        self._entries.append({
            "tool": tool_name,
            "success": success,
            "duration_seconds": round(duration_seconds, 3),
            "reason": reason,
            "timestamp": time.time(),
        })
        if len(self._entries) > self.max_entries:
            self._entries.pop(0)

    def recent(self, limit: int = 10) -> list:
        return self._entries[-limit:]

    def summary(self) -> dict:
        total = len(self._entries)
        succeeded = sum(1 for e in self._entries if e["success"])
        return {
            "total_actions": total,
            "succeeded": succeeded,
            "failed": total - succeeded,
        }


# Module-level singleton, mirroring tools.manager.tool_manager's pattern --
# one shared history per process.
action_history = ActionHistory()


def timed_tool_execute(tm, tool_name: str, parameters: dict):
    """
    Wraps tool_manager.execute() with timing + history recording, without
    changing its return contract. Callers that want history should use
    this instead of calling tool_manager.execute() directly; nothing
    requires it, so existing call sites keep working unmodified.
    """
    start = time.time()
    result = tm.execute(tool_name, parameters)
    duration = time.time() - start
    if result.error != "confirmation_required":  # don't log a pause as an outcome
        action_history.record(
            tool_name=tool_name, success=result.success,
            duration_seconds=duration,
            reason="" if result.success else result.error,
        )
    return result
