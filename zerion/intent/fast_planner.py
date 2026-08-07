# intent/fast_planner.py
"""
Fast Planner: handles requests the Request Classifier has already
determined don't need an LLM call to plan (though the LLM may still be
needed to actually answer/converse -- "zero LLM calls" describes the
planning decision, not necessarily the whole turn).

Handles:
  - a Classification with a confidently matched single tool -> executes
    it directly through the Tool Manager, no LLM round-trip for the
    "which tool?" decision (though tool parameters may still need the
    LLM if they weren't extractable from the text alone -- see note below)
  - MEMORY intent -> looks up the answer directly from long-term memory,
    no LLM call at all
  - SYSTEM intent -> not handled here; main.py's command palette handles
    these before the classifier is even consulted

Anything the Fast Planner doesn't have enough confidence/information to
handle safely returns None, and the caller falls through to the normal
llm.get_llm_output() single-turn path (or the AI Planner, if the
Classification pointed at PLANNER).
"""

import re

from intent.models import Intent
from tools.manager import tool_manager

# Minimum confidence for the Fast Planner to act on a tool match without
# LLM confirmation. Below this, parameters are too uncertain to guess
# safely (e.g. delete_file needs an exact path) -- fall through instead.
_MIN_CONFIDENCE_FOR_DIRECT_EXECUTION = 0.75

# Tools whose single required parameter can often be lifted directly from
# the tail of the user's message without needing the LLM to extract it.
# Conservative list -- only tools where a wrong guess is low-stakes
# (nothing destructive) and the parameter is naturally trailing text.
_SIMPLE_TRAILING_PARAM = {
    "calculate": "expression",
}

# Tools with zero required parameters -- safe to run immediately on a
# confident match with no parameter extraction needed at all.
_ZERO_PARAM_TOOLS = {
    "get_time", "get_date", "generate_uuid", "system_info", "storage_usage",
    "memory_usage", "cpu_info", "network_info", "battery_status",
}


def _extract_trailing_param(user_text: str, tool_name: str) -> dict:
    """Best-effort extraction for the small set of tools where the
    parameter is naturally "whatever comes after the tool-ish words".
    Very conservative -- returns {} (meaning: don't guess) for anything
    not in _SIMPLE_TRAILING_PARAM."""
    param_name = _SIMPLE_TRAILING_PARAM.get(tool_name)
    if not param_name:
        return {}
    # e.g. "calculate 12 * 7" or "what is 12 * 7" -> "12 * 7"
    match = re.search(r"[\d][\d\s()+\-*/.%]*", user_text)
    if match:
        return {param_name: match.group(0).strip()}
    return {}


def try_handle(classification, user_text: str, memory: dict) -> dict:
    """
    Attempt to fully handle this request without an LLM call. Returns a
    result dict shaped like the rest of the system's outputs
    ({"text": ..., "handled_by": "fast_planner", ...}) on success, or
    None if the Fast Planner can't confidently handle it -- caller should
    fall through to the normal LLM path.
    """
    intent = classification.intent

    if intent == Intent.MEMORY:
        return _handle_memory_lookup(user_text, memory)

    if classification.matched_tool and classification.confidence >= _MIN_CONFIDENCE_FOR_DIRECT_EXECUTION:
        return _handle_direct_tool(classification.matched_tool, user_text)

    return None


def _handle_memory_lookup(user_text: str, memory: dict) -> dict:
    """Answer directly from the already-reduced memory dict -- no LLM
    call needed for a plain "what's my name" style question."""
    lowered = user_text.lower()

    if "name" in lowered and memory.get("user_name"):
        return {"text": f"Your name is {memory['user_name']}.", "handled_by": "fast_planner"}

    for key, value in memory.items():
        if key == "user_name":
            continue
        label = key.replace("_", " ")
        if label.split()[0] in lowered or label in lowered:
            return {"text": f"Your {label} is {value}.", "handled_by": "fast_planner"}

    # Nothing matched in memory -- don't guess; let the normal LLM path
    # answer (it may have broader context, or should just say "I don't
    # know that about you yet").
    return None


def _handle_direct_tool(tool_name: str, user_text: str) -> dict:
    tool = tool_manager.get_tool(tool_name)
    if tool is None:
        return None

    if tool_name in _ZERO_PARAM_TOOLS:
        parameters = {}
    elif tool_name in _SIMPLE_TRAILING_PARAM:
        parameters = _extract_trailing_param(user_text, tool_name)
        if not parameters:
            return None  # couldn't extract confidently, let LLM handle it
    else:
        # Any tool needing parameters we can't safely guess (especially
        # destructive ones) is NOT handled here -- falls through to the
        # LLM path, which can ask a clarifying question or extract the
        # right values from full conversational context.
        return None

    result = tool_manager.execute(tool_name, parameters)
    if result.error == "confirmation_required":
        return {"text": result.message, "handled_by": "fast_planner", "confirmation_required": True}

    return {"text": result.message or "", "handled_by": "fast_planner", "tool_used": tool_name}
