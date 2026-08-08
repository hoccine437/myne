# tools/orchestrator_tools.py
"""agent_orchestrate — the Core invokes the canonical orchestrator through
here (the same way conversations reach every tool — through the Tool
Manager). Non-destructive by construction: every lane's whitelisted tools
are read-only, so this tool never bypasses approvals."""

from agents.orchestrator import orchestrator
from agents.orchestrator import AGENT_TYPES
from tools.base import Tool, ToolResult


class AgentOrchestrateTool(Tool):
    name = "agent_orchestrate"
    description = (
        "Orchestrate multiple specialist agents on a complex goal. "
        "Selection is deterministic and minimal-capable; lanes are bounded "
        "by host resources; results are aggregated, critic-reviewed and "
        "telemetry is recorded for future selection. Types: "
        + ", ".join(sorted(AGENT_TYPES)))
    parameters = {"goal": "the objective to orchestrate"}
    destructive = False

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        goal = str((parameters or {}).get("goal", "")).strip()
        if not goal:
            return ToolResult.fail("missing_parameter", "No goal provided.")
        result = orchestrator.run(goal)
        if not result.get("orchestrated"):
            return ToolResult.ok(message=result["message"])
        agg = result["aggregate"]
        headline = f"Orchestrated {len(result['agents'])} agent(s), verdict {result['critic']['verdict']}, confidence {result['confidence']}"
        return ToolResult.ok(data=result, message=headline + "\n" + agg[:600])


class AgentPerformanceTool(Tool):
    name = "agent_performance"
    description = ("Report telemetry collection by agent type and current pool "
                   "capacity/backlog (resource-derived, not hardcoded).")
    parameters = {}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        stats = orchestrator.volume_expectations()
        return ToolResult.ok(data=stats,
                             message=f"pool capacity {stats.get('capacity')}, backlog bound {stats.get('max_pending')}")
