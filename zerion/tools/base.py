# tools/base.py
"""
Abstract base class every tool must implement.

A tool is a single, isolated Python file living in tools/ that subclasses
Tool. The registry (tools/registry.py) discovers every such file
automatically — nothing needs to be manually wired up. See
tools/README.md for the full guide to adding a new tool.
"""

from abc import ABC, abstractmethod


class ToolResult:
    """Structured result every tool execution returns. Never a raw
    exception, never an unstructured value — always this shape."""

    __slots__ = ("success", "data", "message", "error")

    def __init__(self, success: bool, data=None, message: str = "", error: str = ""):
        self.success = success
        self.data = data
        self.message = message
        self.error = error

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data,
            "message": self.message,
            "error": self.error,
        }

    @classmethod
    def ok(cls, data=None, message: str = "") -> "ToolResult":
        return cls(success=True, data=data, message=message, error="")

    @classmethod
    def fail(cls, error: str, message: str = "") -> "ToolResult":
        return cls(success=False, data=None, message=message or error, error=error)

    @classmethod
    def needs_confirmation(cls, message: str, data=None) -> "ToolResult":
        """For destructive operations: signals the caller must confirm
        before the tool will actually perform the action. See
        tools/manager.py for how confirmation is handled."""
        return cls(success=False, data=data, message=message,
                    error="confirmation_required")


class Tool(ABC):
    """
    Every tool must subclass this and implement all abstract members.
    No exceptions — the registry rejects any tool missing one of these.
    """

    #: Short, unique, snake_case identifier (e.g. "get_time"). Used by the
    #: LLM's `intent` field to select this tool.
    name: str = ""

    #: One or two sentences describing what the tool does. Shown to the
    #: LLM so it can decide when to use this tool.
    description: str = ""

    #: Dict describing expected parameters, e.g.
    #: {"expression": "a math expression string to evaluate"}
    #: Empty dict if the tool takes no parameters.
    parameters: dict = {}

    #: If True, this tool performs an irreversible or destructive action
    #: (deleting/moving/overwriting files, running shell commands, etc.)
    #: and must not execute without prior confirmation. See manager.py.
    destructive: bool = False

    @abstractmethod
    def available(self) -> bool:
        """Return True if this tool can run in the current environment
        (right OS, required binary/package present, permissions granted,
        etc.). Must never raise — catch and return False on doubt."""
        raise NotImplementedError

    @abstractmethod
    def execute(self, parameters: dict) -> ToolResult:
        """Run the tool. Must never raise — catch internally and return
        ToolResult.fail(...) on any error. `parameters` is whatever dict
        the LLM (or manager) passed in; validate it defensively."""
        raise NotImplementedError

    def describe(self) -> dict:
        """Metadata sent to the LLM so it knows this tool exists and how
        to call it."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "destructive": self.destructive,
        }
