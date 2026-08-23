# cognition/context.py
"""Context management for the single-blind-spot the prompt builder had:
bounded, relevance-ordered assembly instead of "dump everything we know".

The memory_for_prompt dict passed into llm.get_llm_output(*) may now be
large (capabilities retrieved many rows, orchestration brought evidence,
decision context appended). Assembling all of it verbatim inflates tokens
and buries the signal. assemble() ranks entries by kind, trims each kind,
hierarchical-compresses long bodies, and applies the overall char budget.

Called from llm.get_llm_output on the existing memory_block shape — so the
win applies to BOTH the terminal path and the UI/Web bridge, with no
contract change anywhere else."""

from __future__ import annotations

import config


# ordered by importance for the model's behaviour each turn
_PRIORITY = (
    "_pending_intent", "_collected_params",
    "retrieved_knowledge", "recent_conversation",
    "reasoning_mode", "reasoning_strategy", "reasoning_rules",
    "deep_thinking_protocol", "revisable_hypotheses",
    "user_name", "favorite_color", "favorite_food", "favorite_music",
    "knowledge_gap", "capability_gap", "capability_experience",
    "capability_strategy", "capability_composition", "project_continuity",
    "instruction_context", "device_context",
)

_PER_KEY_MAX = 1200          # chars per individual field
_TOTAL_BUDGET = 6000         # baseline characters for the whole memory block
_HARD_FALLBACK = 60000       # x10 remains bounded even with large memory stores


def assemble(memory_block: dict | None, budget: int | None = None) -> str:
    """Bounded, relevance-ordered rendering of the memory block the Core
    assembled for this turn. Returns the final text block that lands in the
    provider prompt. Never drops the structure keys the runtime relies on."""
    if not memory_block:
        return ""
    # Explicit callers can request a smaller budget (tests/planner previews),
    # while the final model prompt gets the active Think-x10 allowance.
    total_budget = budget if budget is not None else config.thinking_context_budget()
    total_budget = max(1000, min(_HARD_FALLBACK, total_budget))

    items = []
    for key in _PRIORITY:
        if key in memory_block and memory_block[key]:
            items.append((key, str(memory_block[key])))
    # any unexpected key still allowed (forward-compat), goes last
    for key, value in memory_block.items():
        if key not in _PRIORITY and value:
            items.append((key, str(value)))

    out_lines = []
    used = 0
    for key, value in items:
        # hierarchical compression: trim long bodies to head+tail, never drop them
        if len(value) > _PER_KEY_MAX:
            keep = _PER_KEY_MAX // 2
            value = value[:keep] + "\n…(compressed)…\n" + value[-keep:]
        line = f"{key}: {value}"
        if used + len(line) > total_budget:
            remaining = total_budget - used
            if remaining < 120:
                # no room for another meaningful entry — stop cleanly
                out_lines.append(f"… ({len(items) - len(out_lines)} context entries trimmed by budget)")
                break
            line = line[:remaining] + "…"
        out_lines.append(line)
        used += len(line) + 1

    return "\n".join(out_lines)
