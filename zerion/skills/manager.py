from skills.base import Skill
from skills.software import SKILL as SOFTWARE
from skills.finance import SKILL as FINANCE
from skills.electronics import SKILL as ELECTRONICS
from skills.human import SKILL as HUMAN
from skills.domains import ADDITIONAL_DOMAINS, ADDITIONAL_KEYWORDS


class SkillManager:
    """Domain routing + packs. API-compatible with the original legacy
    manager: select(text) returns a Skill with .name."""

    #: legacy keyword routing (unchanged behavior for the original four)
    _LEGACY_KEYS = {
        "financial_markets": ("stock", "market", "invest", "finance"),
        "electronics": ("circuit", "voltage", "resistor", "arduino"),
        "software_engineering": ("code", "python", "bug", "program"),
    }

    def __init__(self, skills=None):
        defaults = [SOFTWARE, FINANCE, ELECTRONICS, HUMAN] + list(ADDITIONAL_DOMAINS)
        self.skills = {x.name: x for x in (skills if skills is not None else defaults)}

    def select(self, text):
        t = (text or "").lower()
        # legacy routing first (preserves original behavior/order)
        for name, keys in self._LEGACY_KEYS.items():
            if any(x in t for x in keys):
                return self.skills[name]
        for name, keys in ADDITIONAL_KEYWORDS.items():
            if name not in self.skills:
                continue
            if any(x in t for x in keys):
                return self.skills[name]
        return self.skills.get("human_knowledge") or next(iter(self.skills.values()))

    def route(self, text) -> dict:
        """Structured routing result for the skill_route tool."""
        skill = self.select(text)
        return {
            "skill": skill.name,
            "categories": list(skill.knowledge_categories),
            "example_tasks": list(skill.reasoning_rules)[:3],
            "prompt": skill.prompt,
        }

    def names(self):
        return sorted(self.skills)
