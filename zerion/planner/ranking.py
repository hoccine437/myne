# planner/ranking.py
"""
Context ranking: scores memory fields, conversation history lines, and
available tools by relevance to the current request, so the Context
Manager sends only the most relevant subset onward rather than
everything it has access to.

This matters concretely: with 30+ tools registered, naively listing
every tool's name and description in every decomposition prompt is real,
avoidable token bloat -- most requests are relevant to at most a handful
of tools. Ranking is rule-based (word-overlap scoring), matching the
same "don't spend an LLM call deciding relevance" principle the Fast
Intent Classifier already uses elsewhere in this codebase.
"""

_MAX_TOOLS_IN_CONTEXT = 12
_MAX_HISTORY_LINES = 5
_MAX_MEMORY_FIELDS = 8


def _word_overlap_score(text_a: str, text_b: str) -> int:
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    return len(words_a & words_b)


def rank_tools(user_text: str, available_tools: list) -> list:
    """
    Return available_tools reordered by relevance to user_text, capped
    at _MAX_TOOLS_IN_CONTEXT. A tool whose name or description shares
    words with the request scores higher. Ties keep the original
    (already availability-filtered) order.

    If the whole tool list already fits under the cap, it's returned
    as-is with no reordering -- ranking only matters once there's
    something to trim.
    """
    if len(available_tools) <= _MAX_TOOLS_IN_CONTEXT:
        return available_tools

    scored = []
    for tool in available_tools:
        haystack = f"{tool.get('name', '')} {tool.get('description', '')}"
        score = _word_overlap_score(user_text, haystack.replace("_", " "))
        scored.append((score, tool))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    ranked = [tool for score, tool in scored[:_MAX_TOOLS_IN_CONTEXT]]
    return ranked


def rank_memory(user_text: str, memory: dict) -> dict:
    """
    Return a trimmed view of `memory` -- only the fields most relevant
    to user_text, capped at _MAX_MEMORY_FIELDS. Fields whose key shares
    a word with the request are scored highest; the rest keep whatever
    order dict iteration gives (stable, not random, in Python).

    If memory already fits under the cap, returned unchanged -- most
    turns have far fewer than 8 memory fields, so this is usually a
    no-op, matching the "never overload the LLM" goal without
    discarding information on the common case.
    """
    if len(memory) <= _MAX_MEMORY_FIELDS:
        return memory

    scored = []
    for key, value in memory.items():
        score = _word_overlap_score(user_text, key.replace("_", " "))
        scored.append((score, key, value))

    scored.sort(key=lambda triple: triple[0], reverse=True)
    return {key: value for _, key, value in scored[:_MAX_MEMORY_FIELDS]}


def rank_history(recent_history: str) -> str:
    """
    Trim conversation history to the most recent _MAX_HISTORY_LINES
    lines. Recency, not relevance scoring, is the right signal for
    conversation history specifically -- the last few exchanges are what
    give a follow-up question its meaning, regardless of word overlap
    with the current message.
    """
    if not recent_history:
        return recent_history
    lines = recent_history.split("\n")
    return "\n".join(lines[-_MAX_HISTORY_LINES:])
