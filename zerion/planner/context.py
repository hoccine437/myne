# planner/context.py
"""
Context Manager: assembles the minimal, relevance-ranked context the
Planner needs before deciding how to handle a request. Reuses main.py's
existing memory-minimization logic for the initial reduction, then
applies planner.ranking on top so only the most relevant subset of
tools/memory reaches the decomposer -- never the whole available set.
"""

from planner import ranking
from tools.manager import tool_manager


class PlanningContext:
    """A snapshot of everything the Planner needs for one turn. Built
    fresh each turn — nothing here is persisted."""

    __slots__ = ("user_text", "memory", "recent_history", "available_tools", "current_goal")

    def __init__(self, user_text: str, memory: dict, recent_history: str,
                 available_tools: list, current_goal: str = None):
        self.user_text = user_text
        self.memory = memory
        self.recent_history = recent_history
        self.available_tools = available_tools
        self.current_goal = current_goal

    def tools_summary(self) -> str:
        if not self.available_tools:
            return "none"
        return ", ".join(t["name"] for t in self.available_tools)


def build_context(user_text: str, minimal_memory: dict, recent_history: str,
                   current_goal: str = None) -> PlanningContext:
    """
    Assemble a PlanningContext for the current turn.

    `minimal_memory` and `recent_history` are passed in already-reduced
    from main.py (which owns that logic via minimal_memory_for_prompt and
    SessionMemory) — this function applies a further relevance-ranking
    pass (planner.ranking) on top: memory fields, tools, and history are
    all trimmed to their most relevant subset for this specific request,
    not just bundled wholesale.
    """
    try:
        tools = tool_manager.list_tools()
    except Exception:
        tools = []

    ranked_tools = ranking.rank_tools(user_text, tools)
    ranked_memory = ranking.rank_memory(user_text, minimal_memory or {})
    ranked_history = ranking.rank_history(recent_history or "")

    return PlanningContext(
        user_text=user_text,
        memory=ranked_memory,
        recent_history=ranked_history,
        available_tools=ranked_tools,
        current_goal=current_goal,
    )
