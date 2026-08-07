# intent/models.py
"""
Shared data structures for the Intent Engine. Kept dependency-free, same
pattern as planner/models.py, to avoid circular imports.
"""

from enum import Enum


class Intent(Enum):
    CHAT = "chat"
    TOOL = "tool"
    MEMORY = "memory"
    PLANNER = "planner"
    AGENT = "agent"          # reserved: multi-turn autonomous action, not yet implemented
    SYSTEM = "system"        # command-palette commands (/status, /help, ...)
    FILE = "file"
    WEB = "web"
    PYTHON = "python"
    SHELL = "shell"
    UNKNOWN = "unknown"


# Tool name -> Intent category, for tools whose category isn't obvious
# from their name alone. Anything not listed here falls back to TOOL.
_CATEGORY_OVERRIDES = {
    "read_file": Intent.FILE, "write_file": Intent.FILE, "search_files": Intent.FILE,
    "list_directory": Intent.FILE, "create_folder": Intent.FILE, "move_file": Intent.FILE,
    "copy_file": Intent.FILE, "delete_file": Intent.FILE, "rename_file": Intent.FILE,
    "http_get": Intent.WEB, "http_post": Intent.WEB, "download_file": Intent.WEB,
    "open_url": Intent.WEB,
    "run_python": Intent.PYTHON,
    "run_shell": Intent.SHELL,
}


def category_for_tool(tool_name: str) -> Intent:
    """Map a tool name to its Intent category, for classification/logging
    purposes. Falls back to the generic TOOL category."""
    return _CATEGORY_OVERRIDES.get(tool_name, Intent.TOOL)


class Classification:
    """Result of classifying one user request."""

    __slots__ = (
        "intent", "confidence", "estimated_tool_count", "needs_reasoning",
        "needs_planning", "needs_memory", "needs_web", "needs_execution",
        "needs_verification", "matched_tool", "reason",
    )

    def __init__(self, intent: Intent, confidence: float = 1.0,
                 estimated_tool_count: int = 0, needs_reasoning: bool = False,
                 needs_planning: bool = False, needs_memory: bool = False,
                 needs_web: bool = False, needs_execution: bool = False,
                 needs_verification: bool = False, matched_tool: str = None,
                 reason: str = ""):
        self.intent = intent
        self.confidence = confidence
        self.estimated_tool_count = estimated_tool_count
        self.needs_reasoning = needs_reasoning
        self.needs_planning = needs_planning
        self.needs_memory = needs_memory
        self.needs_web = needs_web
        self.needs_execution = needs_execution
        self.needs_verification = needs_verification
        self.matched_tool = matched_tool
        self.reason = reason

    def to_dict(self) -> dict:
        return {
            "intent": self.intent.value,
            "confidence": self.confidence,
            "estimated_tool_count": self.estimated_tool_count,
            "needs_reasoning": self.needs_reasoning,
            "needs_planning": self.needs_planning,
            "needs_memory": self.needs_memory,
            "needs_web": self.needs_web,
            "needs_execution": self.needs_execution,
            "needs_verification": self.needs_verification,
            "matched_tool": self.matched_tool,
            "reason": self.reason,
        }
