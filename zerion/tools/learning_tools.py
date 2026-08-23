# tools/learning_tools.py
"""Learning tools: the conversation can trigger the LearningController
through the existing Tool Manager — same path as everything else.

learn_domain   — run topic-specific study (bounded, evidence-gated)
learn_progress — multi-dimensional progress summary
review_due     — spaced-recall due list
"""

from __future__ import annotations

from learning.controller import LearningController
from learning.retention import RetentionScheduler
from tools.base import Tool, ToolResult

_controller = None


def _ctrl() -> LearningController:
    global _controller
    if _controller is None:
        _controller = LearningController()
    return _controller


class LearnDomainTool(Tool):
    name = "learn_domain"
    description = ("Study a domain through the evidence-gated learning loop: assess → "
                   "gaps → curriculum → practice → feedback → verify → generalize → "
                   "record. A subject-specific teacher/exercise or source evidence is "
                   "required; generic arithmetic is never used as domain mastery. "
                   "Bounded (max 6 iterations per call), never self-verified without evidence.")
    parameters = {"topic": "the domain to learn",
                  "known_concepts": "optional list of already-known concepts",
                  "source_text": "optional reference material to study",
                  "source_url": "optional reference URL (orientation only unless fetched separately)"}
    destructive = False

    def available(self) -> bool: return True

    def execute(self, parameters: dict) -> ToolResult:
        topic = str((parameters or {}).get("topic", "")).strip()
        if not topic:
            return ToolResult.fail("missing_parameter", "No topic provided.")
        params = parameters or {}
        known = params.get("known_concepts")
        try:
            report = _ctrl().study_domain(
                topic,
                known_concepts=list(known or []),
                source_text=str(params.get("source_text", "") or ""),
                source_url=str(params.get("source_url", "") or ""),
            )
        except Exception as e:
            return ToolResult.fail("learning_failed", str(e))
        level = report.get("final_level", {})
        if report.get("finished_reason") in ("needs-domain-evidence", "teacher-unavailable"):
            return ToolResult.ok(
                data=report,
                message=(f"Study request for {topic!r} was not marked as learned: "
                         f"{report.get('message', 'a topic-specific teacher is required')} "
                         "No mastery or verification claim was made."),
            )
        if report.get("finished_reason") == "studied-unverified":
            checks = sum(i.get("checks", 0) for i in report.get("iterations", []))
            return ToolResult.ok(
                data=report,
                message=(f"Studied {topic!r}: {len(report.get('iterations', []))} topic lesson(s) "
                         f"and {checks} recall check(s) stored. Material remains UNVERIFIED; "
                         "no mastery claim was made."),
            )
        return ToolResult.ok(data=report,
                             message=(f"learned {topic}: mastery {level.get('mastery')} "
                                      f"verify-rate {level.get('verify_rate')} "
                                      f"generalization {report['generalization']['score']} "
                                      f"({report['finished_reason']})"))


class LearnProgressTool(Tool):
    name = "learn_progress"
    description = "Report learning progress for the most recent runs (multi-dimensional)."
    parameters = {}
    destructive = False

    def available(self) -> bool: return True

    def execute(self, parameters: dict) -> ToolResult:
        rows = _ctrl().km.db.query(
            "SELECT metadata, created FROM records WHERE layer='learning_progress' "
            "ORDER BY created DESC LIMIT 10")
        import json as _json
        out = []
        for r in rows:
            meta = _json.loads(r["metadata"]) if isinstance(r["metadata"], str) else (r["metadata"] or {})
            out.append({"event": meta.get("event"),
                        "topic": meta.get("objective", {}).get("topic"),
                        "skill_levels": meta.get("objective", {}).get("skill_levels"),
                        "ts": meta.get("ts")})
        return ToolResult.ok(data=out,
                             message=f"{len(out)} recent learning record(s)")


class ReviewDueTool(Tool):
    name = "review_due"
    description = "Which learned items are due for spaced recall right now."
    parameters = {}
    destructive = False

    def available(self) -> bool: return True

    def execute(self, parameters: dict) -> ToolResult:
        due = RetentionScheduler().due()
        return ToolResult.ok(data=due,
                             message=f"{len(due)} item(s) due for review")
