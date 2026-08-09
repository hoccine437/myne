# tools/manager.py
"""
The Tool Manager is the single entry point main.py talks to. It loads the
tool registry, validates that every discovered tool is well-formed, exposes
tool descriptions for the LLM, and executes tools on request.

The manager also owns the confirmation flow for destructive tools (delete,
move, shell/python execution): the first call to a destructive tool
returns a "confirmation_required" result instead of running, and only
executes once the same tool+parameters are confirmed. main.py is
responsible for asking the user and calling confirm_and_execute().
"""

from copy import deepcopy

from tools.base import ToolResult
from tools.registry import discover
from constitution.policy import Constitution


class ToolManager:
    def __init__(self):
        self._tools = None          # lazy: populated on first use
        self._pending_confirmation = None  # (tool_name, parameters) awaiting yes/no

    # -- loading -------------------------------------------------------

    def _ensure_loaded(self):
        if self._tools is None:
            self._tools = discover()

    def list_tools(self) -> list:
        """Return metadata for every available tool, for the LLM prompt."""
        self._ensure_loaded()
        result = []
        for tool in self._tools.values():
            try:
                if tool.available():
                    result.append(tool.describe())
            except Exception:
                continue  # a tool whose available() check itself fails is treated as unavailable
        return result

    def get_tool(self, name: str):
        self._ensure_loaded()
        return self._tools.get(name)

    # -- execution -------------------------------------------------------

    def execute(self, name: str, parameters: dict = None) -> ToolResult:
        """Execute a tool by name. Destructive tools return a
        confirmation_required result on first call instead of running."""
        self._ensure_loaded()
        parameters = parameters or {}

        tool = self._tools.get(name)
        if tool is None:
            return ToolResult.fail(
                error="unknown_tool",
                message=f"No tool named '{name}' is available.",
            )

        try:
            if not tool.available():
                return ToolResult.fail(
                    error="unavailable",
                    message=f"'{name}' isn't available in this environment.",
                )
        except Exception as e:
            return ToolResult.fail(
                error="availability_check_failed",
                message=f"Could not check availability of '{name}': {e}",
            )

        pending_key = (name, _freeze(parameters))
        if tool.destructive:
            # Every consequential tool traverses the constitutional policy;
            # the existing confirmation flow supplies the required approval.
            action = "execute_python" if name == "run_python" else "execute_shell" if name == "run_shell" else "modify"
            decision = Constitution().evaluate(action)
            if not decision.allowed:
                return ToolResult.fail(error="constitution_denied", message=decision.reason)
        if tool.destructive and (self._pending_confirmation is None or self._pending_confirmation[:2] != pending_key):
            # Retain original parameter types for the confirmed execution.
            # `_freeze` is comparison-only and stringifies nested values.
            self._pending_confirmation = (*pending_key, deepcopy(parameters))
            return ToolResult.needs_confirmation(
                message=f"'{name}' will make a permanent change. Reply 'confirm' to proceed, "
                        f"or anything else to cancel.",
                data={"tool": name, "parameters": parameters},
            )

        # Either non-destructive, or this exact call was just confirmed.
        self._pending_confirmation = None

        try:
            from core.events import bus as _core_events
            _core_events.emit("tool.called", {"tool": name})
            result = tool.execute(parameters)
            if not isinstance(result, ToolResult):
                return ToolResult.fail(
                    error="invalid_tool_result",
                    message=f"'{name}' returned an invalid result type.",
                )
            if not result.success and result.error != "confirmation_required":
                _core_events.emit("tool.failed",
                                  {"tool": name, "error": result.error})
            return result
        except Exception as e:
            try:
                from core.events import bus as _core_events
                _core_events.emit("tool.failed",
                                  {"tool": name, "error": str(e)[:120]})
            except Exception:
                pass
            return ToolResult.fail(
                error="execution_failed",
                message=f"'{name}' failed to run: {e}",
            )

    def has_pending_confirmation(self) -> bool:
        return self._pending_confirmation is not None

    def cancel_pending_confirmation(self) -> None:
        self._pending_confirmation = None

    def confirm_pending(self) -> ToolResult:
        """Execute whatever destructive call is currently awaiting
        confirmation. Returns a fail result if nothing is pending."""
        if self._pending_confirmation is None:
            return ToolResult.fail(error="nothing_pending", message="No action is awaiting confirmation.")
        name, _frozen_params, original_params = self._pending_confirmation
        return self.execute(name, original_params)


def _freeze(parameters: dict) -> tuple:
    """Make a dict hashable/comparable for pending-confirmation matching."""
    return tuple(sorted((k, str(v)) for k, v in parameters.items()))


# Module-level singleton — main.py imports and uses this directly, so
# there's exactly one tool manager (and one pending-confirmation slot)
# per process, matching the single-session terminal loop.
tool_manager = ToolManager()
