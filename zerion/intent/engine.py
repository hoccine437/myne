# intent/engine.py
"""
Intent Engine: the single entry point main.py calls before any LLM work
happens. Classifies the request (zero LLM cost) and, if the Fast Planner
can fully handle it (also zero LLM cost, except MEMORY lookups and
zero/simple-parameter tool calls), returns the answer immediately.

If neither can handle it, returns (classification, None) -- the caller
uses the classification to decide whether to go straight to the normal
llm.get_llm_output() path or escalate to the AI Planner
(planner.planner.handle_request), per the classification's
`needs_planning` flag.
"""

from intent.classifier import classify
from intent.fast_planner import try_handle as fast_planner_try_handle
from intent.history import action_history
from tools.manager import tool_manager


def process(user_text: str, memory: dict):
    """
    Returns (classification, fast_result). fast_result is a dict (see
    intent/fast_planner.py's try_handle docstring) if the Fast Planner
    fully handled this request, or None if it needs to go to the LLM
    (either the normal chat path or the AI Planner).
    """
    try:
        available_tools = tool_manager.list_tools()
    except Exception:
        available_tools = []

    classification = classify(user_text, available_tools)

    fast_result = None
    try:
        fast_result = fast_planner_try_handle(classification, user_text, memory)
    except Exception as e:
        print(f"(intent engine: fast planner failed, falling back: {e})")
        fast_result = None

    if fast_result and fast_result.get("tool_used"):
        action_history.record(
            tool_name=fast_result["tool_used"], success=True, duration_seconds=0.0,
        )

    return classification, fast_result
