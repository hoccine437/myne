# intent/classifier.py
"""
Request Classifier: rule-based, zero-LLM-cost classification of a user
request into an Intent category plus complexity signals (estimated tool
count, need for reasoning/planning/memory/web/execution/verification).

This is deliberately simple pattern matching, not an LLM call — the
whole point is to make the "is this simple?" decision essentially free,
so the expensive path (AI Planner) is only reached when there's real
signal that it's needed. False negatives (missing a genuinely complex
request) are recoverable — planner/decomposer.py's own LLM-based check
is still the safety net for anything this misses when PLANNER_ENABLED
is on. False positives (flagging something complex that wasn't) just
cost one extra decomposition call, not incorrect behavior.
"""

from intent.models import Classification, Intent, category_for_tool

_SYSTEM_COMMANDS = {
    "/status", "/tools", "/memory", "/history", "/goals",
    "/plugins", "/debug", "/help", "/plan",
}

_MULTI_STEP_MARKERS = (
    " then ", " after that", " and then", " next ", " followed by",
    "first,", "step 1", "step one",
)

_MEMORY_MARKERS = (
    "remember", "what's my name", "what is my name", "who am i",
    "my favorite", "do you know my", "recall",
)

_WEB_MARKERS = ("http://", "https://", "download", "fetch url", "search the web", "search online")

_FILE_MARKERS = ("file", "folder", "directory", "read the", "write to", "save to", "delete the")

_SHELL_MARKERS = ("run shell", "shell command", "terminal command", "execute command")

_PYTHON_MARKERS = ("run python", "python code", "python script", "execute python")


def _count_conjunctions(text: str) -> int:
    """Rough proxy for "how many separate actions is this asking for" —
    counts multi-step marker phrases. Not linguistically rigorous; good
    enough as a cheap signal to escalate to the LLM-based decomposer."""
    lowered = text.lower()
    return sum(1 for marker in _MULTI_STEP_MARKERS if marker in lowered)


def classify(user_text: str, available_tools: list = None) -> Classification:
    """
    Classify a user request without calling the LLM. `available_tools`
    is the same list shape as tools.manager.tool_manager.list_tools() —
    used to detect an exact/near tool-name match for single-tool routing.
    """
    text = (user_text or "").strip()
    lowered = text.lower()
    available_tools = available_tools or []

    if not text:
        return Classification(Intent.UNKNOWN, confidence=1.0, reason="empty input")

    # --- SYSTEM: command palette, always highest priority, exact match ---
    first_word = lowered.split()[0] if lowered.split() else ""
    if first_word in _SYSTEM_COMMANDS:
        return Classification(Intent.SYSTEM, confidence=1.0, reason="command palette")

    # --- Multi-step detection: route to PLANNER before anything else ---
    conjunctions = _count_conjunctions(text)
    if conjunctions >= 1:
        return Classification(
            Intent.PLANNER, confidence=0.7, estimated_tool_count=2 + conjunctions,
            needs_planning=True, needs_reasoning=True, needs_verification=True,
            reason=f"detected {conjunctions} multi-step marker(s)",
        )

    # --- MEMORY: asking about something previously told to the assistant ---
    if any(marker in lowered for marker in _MEMORY_MARKERS):
        return Classification(Intent.MEMORY, confidence=0.8, needs_memory=True,
                               reason="memory-recall phrasing")

    # --- Direct tool-name match: single TOOL (or its sub-category) ---
    best_match = None
    best_overlap = 0
    for tool in available_tools:
        name = tool.get("name", "")
        if not name:
            continue
        name_words = set(name.split("_"))
        overlap = len(name_words & set(lowered.replace(",", " ").split()))
        if overlap > best_overlap:
            best_overlap = overlap
            best_match = name

    if best_match and best_overlap >= 2:
        category = category_for_tool(best_match)
        return Classification(
            category, confidence=0.75, estimated_tool_count=1,
            needs_execution=True, needs_verification=True,
            matched_tool=best_match, reason=f"matched tool name '{best_match}' ({best_overlap} word overlap)",
        )

    # --- Category keyword fallbacks (no exact tool name matched, but the
    # phrasing strongly suggests one of these categories; let the normal
    # LLM intent field make the final tool choice) ---
    if any(marker in lowered for marker in _SHELL_MARKERS):
        return Classification(Intent.SHELL, confidence=0.6, needs_execution=True,
                               needs_verification=True, reason="shell-execution phrasing")
    if any(marker in lowered for marker in _PYTHON_MARKERS):
        return Classification(Intent.PYTHON, confidence=0.6, needs_execution=True,
                               needs_verification=True, reason="python-execution phrasing")
    if any(marker in lowered for marker in _WEB_MARKERS):
        return Classification(Intent.WEB, confidence=0.6, needs_web=True,
                               needs_execution=True, reason="web-access phrasing")
    if any(marker in lowered for marker in _FILE_MARKERS):
        return Classification(Intent.FILE, confidence=0.5, needs_execution=True,
                               reason="file-operation phrasing")

    # --- Default: ordinary conversation ---
    word_count = len(text.split())
    return Classification(
        Intent.CHAT, confidence=0.9 if word_count <= 15 else 0.6,
        needs_reasoning=word_count > 15,
        reason="no tool/planning signal detected",
    )
