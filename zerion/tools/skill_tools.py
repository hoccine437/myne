# tools/skill_tools.py
"""Domain routing through the Tool Manager: classifies a request into a
skill domain and returns the domain pack (focus, examples, cautions).
Genuinely usable by the Core's intent contract — the LLM can set
intent='skill_route' to get domain guidance, or users can ask directly."""

from skills.manager import SkillManager
from tools.base import Tool, ToolResult

_manager = None


def _mgr() -> SkillManager:
    global _manager
    if _manager is None:
        _manager = SkillManager()
    return _manager


class SkillRouteTool(Tool):
    name = "skill_route"
    description = ("Classify a request into a knowledge domain (mathematics, "
                   "physics, chemistry, health information, legal information, "
                   "culinary, languages, history, mechanical engineering, writing, "
                   "software, finance, electronics, human knowledge) and return "
                   "domain guidance, example tasks, and cautions.")
    parameters = {"text": "the request to route"}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        text = str((parameters or {}).get("text", "")).strip()
        if not text:
            return ToolResult.fail(error="missing_parameter", message="No text provided.")
        info = _mgr().route(text)
        examples = "; ".join(info["example_tasks"])
        return ToolResult.ok(
            data=info,
            message=f"Domain: {info['skill']}. Example tasks: {examples}",
        )


class SkillListTool(Tool):
    name = "skill_list"
    description = "List all available skill domains the Core can route into."
    parameters = {}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        names = _mgr().names()
        return ToolResult.ok(data=names, message=f"{len(names)} domains: " + ", ".join(names))
