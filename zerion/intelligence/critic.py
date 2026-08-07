# intelligence/critic.py
"""
Self-Critic: reviews a draft response before it reaches the user, and
improves it once if the review finds a real problem. Additive -- runs
after llm.get_llm_output() returns and before main.py speaks/logs the
result.

Design constraints (matching the rest of this codebase):
  - Never invents facts about what happened; only checks the text itself
    and the confidence signal already computed this turn by
    cognition.reasoning.CognitiveReasoningEngine (no second, competing
    confidence number).
  - Structural checks are free (no LLM call). An improve-pass only fires
    when review() actually flags a problem, so the common case (a normal,
    confident answer) costs nothing extra.
  - The improve-pass is a single bounded api.call_llm() -- same transport
    llm.py already uses -- not a new prompt-building/JSON-contract path.
  - Never raises: any failure here must fall back to the original draft,
    since a broken critic must not be able to block a response.

No feedback loop:
  - improve() runs at most config.MAXIMUM_IMPROVEMENT_ATTEMPTS times
    (default 1) per call, and never calls review() or itself again on its
    own output. main.py calls review() once and improve() at most once
    per turn -- the improved text is used as-is, whether or not it would
    still be flagged if re-reviewed. There is no recursion anywhere in
    this module.

Extensibility:
  - Each structural check is an independent function of the form
    (goal, response, confidence) -> Issue | None, registered in
    _REVIEW_RULES. Adding a new rule means writing one function and
    appending it to that list -- no existing rule or the review() loop
    itself needs to change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import api
import config
from core import logging as log
from knowledge.manager import KnowledgeManager

# ---------------------------------------------------------------------------
# Structured issue / result types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Issue:
    type: str
    severity: str  # "low" | "medium" | "high"
    description: str
    suggested_fix: str


@dataclass(frozen=True)
class CritiqueResult:
    should_improve: bool
    issues: tuple[Issue, ...] = field(default_factory=tuple)
    confidence: float = 0.5

    @property
    def reasons(self) -> tuple[str, ...]:
        """Backward-compatible plain-text view of issues, for callers/logs
        that just want a short human-readable summary."""
        return tuple(issue.description for issue in self.issues)


# ---------------------------------------------------------------------------
# Review rules -- each one independent, each returns Issue | None.
# To add a new check: write a function with this signature and append it
# to _REVIEW_RULES. Nothing else in this file needs to change.
# ---------------------------------------------------------------------------

_ReviewRule = Callable[[str, str, float], Optional[Issue]]

_CONTRADICTION_MARKERS = (
    ("i can", "i can't"), ("i can", "i cannot"),
    ("yes,", "no,"), ("i did", "i didn't"), ("i did", "i can't"),
)

# Claims of a completed action the model cannot actually verify from a plain
# chat turn (no tool ran) -- catches the LLM narrating a false success.
_UNVERIFIED_ACTION_MARKERS = (
    "i've sent", "i have sent", "i've saved", "i have saved",
    "i've deleted", "i have deleted", "i've called", "i have called",
    "i've booked", "i have booked", "i've updated", "i have updated",
)


def _rule_empty_response(goal: str, response: str, confidence: float) -> Optional[Issue]:
    if not response.strip():
        return Issue(
            type="empty_response",
            severity="high",
            description="empty response",
            suggested_fix="Provide a direct answer to the user's request.",
        )
    return None


def _rule_too_short(goal: str, response: str, confidence: float) -> Optional[Issue]:
    text = response.strip()
    if text and len(text) < config.MINIMUM_RESPONSE_LENGTH:
        return Issue(
            type="too_short",
            severity="medium",
            description="response too short to be useful",
            suggested_fix="Expand the response with enough detail to actually answer the request.",
        )
    return None


def _rule_contradiction(goal: str, response: str, confidence: float) -> Optional[Issue]:
    low = response.lower()
    for a, b in _CONTRADICTION_MARKERS:
        if a in low and b in low:
            return Issue(
                type="contradiction",
                severity="high",
                description=f"possible self-contradiction ('{a}' / '{b}')",
                suggested_fix="Resolve the contradiction and state one consistent answer.",
            )
    return None


def _rule_unverified_action(goal: str, response: str, confidence: float) -> Optional[Issue]:
    low = response.lower()
    for marker in _UNVERIFIED_ACTION_MARKERS:
        if marker in low:
            return Issue(
                type="unverified_action_claim",
                severity="high",
                description=f"claims a completed action ('{marker}') with no tool call this turn",
                suggested_fix="Do not claim the action was performed; either perform it via a tool or say it wasn't done.",
            )
    return None


def _rule_cutoff(goal: str, response: str, confidence: float) -> Optional[Issue]:
    text = response.strip()
    if text and text[-1] not in ".!?\"')]" and len(text) > 40:
        return Issue(
            type="cutoff",
            severity="low",
            description="response appears to be cut off mid-sentence",
            suggested_fix="Complete the final sentence or thought.",
        )
    return None


def _rule_low_confidence(goal: str, response: str, confidence: float) -> Optional[Issue]:
    if confidence < config.LOW_CONFIDENCE_THRESHOLD:
        return Issue(
            type="low_confidence",
            severity="medium",
            description=f"low reasoning confidence ({confidence:.2f})",
            suggested_fix="Verify the claim, ask a clarifying question, or note the uncertainty explicitly.",
        )
    return None


# Registration order only affects which issue is logged first; every rule
# still runs and all issues are collected, so order has no effect on
# should_improve or on which issues are reported.
_REVIEW_RULES: tuple[_ReviewRule, ...] = (
    _rule_empty_response,
    _rule_too_short,
    _rule_contradiction,
    _rule_unverified_action,
    _rule_cutoff,
    _rule_low_confidence,
)


# ---------------------------------------------------------------------------
# Self-Critic
# ---------------------------------------------------------------------------

class SelfCritic:
    def __init__(self, knowledge: KnowledgeManager = None):
        # Structured critique log, reusing the project's existing
        # SQLite-backed knowledge store rather than inventing a second
        # persistence mechanism (knowledge/database.py already gives
        # every record a timestamp, and search.py makes them queryable
        # later for debugging or future learning).
        self.knowledge = knowledge or KnowledgeManager()

    def review(self, goal: str, response: str, confidence: float) -> CritiqueResult:
        """Run every registered rule independently. Never raises --
        returns a no-issues result on any internal error rather than
        blocking the turn."""
        try:
            return self._review(goal, response, confidence)
        except Exception as e:
            log.warning(f"self-critic review failed, skipping: {e}")
            return CritiqueResult(should_improve=False, confidence=confidence)

    def _review(self, goal: str, response: str, confidence: float) -> CritiqueResult:
        text = response or ""
        issues = []
        for rule in _REVIEW_RULES:
            try:
                issue = rule(goal, text, confidence)
            except Exception as e:
                # One bad rule must not take down the others.
                log.warning(f"self-critic rule {rule.__name__!r} failed: {e}")
                issue = None
            if issue is not None:
                issues.append(issue)

        result = CritiqueResult(
            should_improve=bool(issues),
            issues=tuple(issues),
            confidence=confidence,
        )
        if result.should_improve:
            self._log_critique(goal, text, result)
        return result

    def improve(self, goal: str, response: str, critique: CritiqueResult) -> str:
        """At most one rewrite pass -- config.MAXIMUM_IMPROVEMENT_ATTEMPTS
        (default 1) -- and never calls review() or improve() again on its
        own output. Returns the original response unchanged if improvement
        is disabled (max attempts is 0) or on any failure, so an improve
        attempt can never lose the draft the user would otherwise get."""
        if not critique.should_improve or config.MAXIMUM_IMPROVEMENT_ATTEMPTS < 1:
            return response
        try:
            issues_text = "; ".join(
                f"[{issue.severity}] {issue.description} (fix: {issue.suggested_fix})"
                for issue in critique.issues
            )
            system_prompt = (
                "You are a careful editor. You will be shown a user request and a "
                "draft reply, plus specific issues found in the draft. Rewrite the "
                "reply to fix exactly those issues. Keep the same length and tone. "
                "Do not add caveats or mention that this is a revision. Reply with "
                "the corrected text only -- no preamble, no explanation."
            )
            user_prompt = (
                f'User request: "{goal}"\n\n'
                f'Draft reply: "{response}"\n\n'
                f"Issues found: {issues_text}"
            )
            revised = api.call_llm(system_prompt, user_prompt)
            revised = (revised or "").strip()
            # Whatever comes back -- even if it would still trip a rule on
            # re-review -- is kept as-is and returned. No re-review, no
            # second attempt, no recursion: this is the one and only pass.
            return revised or response
        except Exception as e:
            log.warning(f"self-critic improve pass failed, keeping original: {e}")
            return response

    def _log_critique(self, goal: str, response: str, critique: CritiqueResult) -> None:
        """Persist a structured record of this critique for later
        debugging/learning. Best-effort: a logging failure must never
        affect the turn."""
        try:
            self.knowledge.store(
                content=f"critique for: {goal[:200]}",
                category="self_critique",
                tags=[issue.type for issue in critique.issues],
                importance=0.4,
                confidence=critique.confidence,
                metadata={
                    "goal": goal,
                    "response_preview": response[:300],
                    "confidence": critique.confidence,
                    "issues": [
                        {
                            "type": issue.type,
                            "severity": issue.severity,
                            "description": issue.description,
                            "suggested_fix": issue.suggested_fix,
                        }
                        for issue in critique.issues
                    ],
                },
                layer="critique",
            )
        except Exception as e:
            log.warning(f"self-critic: failed to log critique: {e}")


# Module-level singleton, matching tool_manager/reasoning's pattern of one
# shared instance per process.
self_critic = SelfCritic()
