# learning/triggers.py
"""Runtime triggers into the canonical LearningController.

This module owns ONLY the "should we learn right now, and is it allowed?"
decision. The loop itself lives in learning/controller.py — nothing here
re-implements acquisition, practice, verification, or storage.

Trigger policy (conservative, offline-first, importance-thresholded):

1. EXPLICIT — the user says "learn <topic>" / "teach yourself <topic>".
   The only trigger that starts topic-specific study in-band, because it is
   user-commanded. With the shared Gemini key it asks the provider for a
   bounded lesson and recall checks; with supplied material it can ingest
   offline. Generated/source material stays UNVERIFIED until independent
   evidence or tested recall promotes it.

2. OBSERVED FAILURE PATTERN — the same tool failing repeatedly in this
   session's action history. Produces a surfaced *signal* (logs + report),
   never silent background study: the proposal text tells the user the
   exact command to run. Learning-on-every-failure is explicitly NOT done
   here (relevance threshold: REPEATED_FAILURE_MIN failures of one tool).

User corrections ("that's wrong", "no, ...") deliberately do NOT auto-learn:
a bare correction has no verified replacement content; it is handled by the
conversation path, and the failure side is captured by the tool-failure
signal above.

Returns fast_result-shaped dicts so both front ends (main.py's terminal
loop and ui/session.py's bridge) display them with zero contract change.
"""

from __future__ import annotations

import re

from core import logging as log

# Explicit-study markers: the request must START with one of these, so
# mid-sentence "…so I can learn X" conversations are never intercepted.
_LEARN_PREFIXES = ("learn ", "teach yourself ")

# How many failures of one tool (this session) before the system says so.
REPEATED_FAILURE_MIN = 3


def _topic_and_source(text: str) -> tuple[str, str] | None:
    lowered = text.strip().lower()
    for prefix in _LEARN_PREFIXES:
        if lowered.startswith(prefix):
            topic = text.strip()[len(prefix):].strip()
            match = re.match(r"^(.+?)\s+(?:from|using)\s+(https?://\S+)$", topic,
                             flags=re.IGNORECASE)
            if match:
                topic, source_url = match.group(1).strip(), match.group(2).strip()
            else:
                source_url = ""
            if len(topic) >= 3:
                return topic, source_url
    return None


def _topic_after_prefix(text: str) -> str | None:
    parsed = _topic_and_source(text)
    return parsed[0] if parsed else None


def evaluate(user_text: str, memory: dict | None = None) -> dict | None:
    """Return a fast_result dict when a trigger fired and produced the full
    answer for this turn, else None (caller proceeds exactly as before)."""

    # --- trigger 2: repeated-failure pattern → honest surfaced signal ----
    # Checked on every turn that reaches us; pure observation, no execution.
    try:
        from intent.history import action_history
        recent = action_history.recent(limit=50)
        by_tool: dict[str, int] = {}
        for entry in recent:
            if not entry.get("success"):
                by_tool[entry["tool"]] = by_tool.get(entry["tool"], 0) + 1
        for tool, fails in by_tool.items():
            if fails >= REPEATED_FAILURE_MIN:
                log.info(
                    f"learning trigger: '{tool}' failed {fails} times this session — "
                    f"a study pass may help (`/learn {tool}` or 'learn {tool}').")
                break  # one signal per turn; more is noise
    except Exception:
        pass  # the signal must never affect the conversation path

    # --- trigger 1: explicit user-commanded study -------------------------
    parsed_request = _topic_and_source(user_text)
    if parsed_request is None:
        return None
    topic, source_url = parsed_request

    try:
        from learning.controller import LearningController
        # Production study must use a topic-specific teacher. The old
        # callback-free learning loop was a synthetic arithmetic experiment,
        # not a Kali Linux (or any other domain) teacher.
        report = LearningController().study_domain(topic, source_url=source_url)
    except Exception as e:
        return {"text": f"Learning session for '{topic}' could not run: {e}",
                "handled_by": "learning", "tool_used": "learn_domain"}

    level = report.get("final_level", {})
    iters = report.get("iterations", [])
    if report.get("finished_reason") in ("needs-domain-evidence", "teacher-unavailable"):
        text = (
            f"Study request for '{topic}' was not marked as learned: "
            f"{report.get('message', 'a topic-specific teacher is required')} "
            "No mastery or verification claim was made."
        )
        return {"text": text, "handled_by": "learning", "tool_used": "learn_domain",
                "learning": {"topic": topic, "iterations": 0, "errors": 0,
                             "final_level": level,
                             "finished_reason": report.get("finished_reason")}}

    if report.get("finished_reason") == "studied-unverified":
        text = (
            f"Studied '{topic}': {len(iters)} topic lesson(s) generated and stored, "
            f"{sum(i.get('checks', 0) for i in iters)} recall check(s), "
            "verification 0.0 — material remains UNVERIFIED until independent "
            "evidence or tested recall promotes it. No mastery claim was made."
        )
        return {"text": text, "handled_by": "learning", "tool_used": "learn_domain",
                "learning": {"topic": topic, "iterations": len(iters), "errors": 0,
                             "final_level": level,
                             "finished_reason": report.get("finished_reason")}}

    # the deterministic experiment reports per-iteration verdicts; failed attempts are the errors
    errors = [i for i in iters if not i.get("correct")]
    gen = report.get("generalization") or {}
    text = (
        f"Studied '{topic}': {len(iters)} learning step(s), "
        f"{len(errors)} recorded error(s), "
        f"generalization {gen.get('score', '?')} on unseen probes, "
        f"verify-rate {level.get('verify_rate', '?')} "
        f"(records stay UNVERIFIED until evidence promotes them). "
        f"Finished: {report.get('finished_reason', '?')}."
    )
    return {"text": text, "handled_by": "learning", "tool_used": "learn_domain",
            "learning": {"topic": topic, "iterations": len(iters),
                         "errors": len(errors), "final_level": level,
                         "finished_reason": report.get("finished_reason")}}
