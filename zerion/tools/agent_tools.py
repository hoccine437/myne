# tools/agent_tools.py
"""Agent delegation tool: main.py's LLM/planner can hand a bounded
subtask to an agent instance without leaving the Tool Manager path.

Non-destructive by construction: the pool refuses anything whose tool is
not on the agent type's whitelist (whitelists never contain destructive
tools — those stay on the human-confirmed path).
"""

from agents.service import pool
from agents.types import AGENT_TYPES
from tools.base import Tool, ToolResult


class AgentDelegateTool(Tool):
    name = "agent_delegate"
    description = (
        "Delegate one bounded subtask to a specialized agent instance. Types: "
        + ", ".join(AGENT_TYPES) +
        ". Subtasks are either {'tool': whitelisted_tool, 'parameters': {...}} "
        "or {'query': text} for memory-capable agents. Destructive operations "
        "are never delegated — they require the supervised confirmation path.")
    parameters = {
        "agent_type": "one of: " + ", ".join(AGENT_TYPES),
        "task": "dict with 'tool' + optional 'parameters', or 'query' string",
        "wait": "optional bool — wait for the result (default true)",
    }
    destructive = False

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        if not isinstance(parameters, dict):
            return ToolResult.fail(error="invalid_parameters", message="expected a dict")
        agent_type = str(parameters.get("agent_type", "")).strip().lower()
        task = parameters.get("task")
        wait = bool(parameters.get("wait", True))

        if agent_type not in AGENT_TYPES:
            return ToolResult.fail(
                error="unknown_agent_type",
                message=f"Unknown agent_type '{agent_type}'. Valid: {', '.join(AGENT_TYPES)}")
        if not isinstance(task, dict) or ("tool" not in task and "query" not in task):
            return ToolResult.fail(
                error="invalid_task",
                message="task must be a dict with 'tool' (+parameters) or 'query'.")

        result = pool.spawn(agent_type, task, wait=wait)
        if not result.get("ok"):
            return ToolResult.fail(error=str(result.get("error", "failed")),
                                   message=str(result.get("message", "agent delegation failed")))
        agent = result["agent"]
        if agent.get("status") == "failed":
            return ToolResult.fail(error="agent_failed",
                                   message=agent.get("error") or "agent failed",
                                   )
        if not wait:
            return ToolResult.ok(data={"agent_id": agent["id"], "status": agent["status"]},
                                 message=f"Agent {agent['id']} ({agent_type}) started.")
        res = agent.get("result") or {}
        return ToolResult.ok(data={"agent_id": agent["id"], **(res if isinstance(res, dict) else {"result": res})},
                             message=str(res.get("message", "done")))


class AgentStatusTool(Tool):
    name = "agent_status"
    description = "Report live agent instances, capacity, and recent outcomes."
    parameters = {}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        stats = pool.stats()
        return ToolResult.ok(data=stats,
                             message=f"agents: {stats['tracked']} tracked, capacity {stats['capacity']}")
