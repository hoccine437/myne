# core/turn_pipeline.py
"""Shared conversation-turn semantics — the one place the terminal loop
(main.py:run_loop) and the UI bridge (ui/session.py) agree on turn
contract details.

What belongs here: the MINIMAL, decisively shared rules — confirmation
vocabulary, interrupt words, the plan-summary prose shape. What does NOT
belong here: anything about how output is displayed (main prints and
speaks; the UI emits bus events). That presentation divergence is
intentional and must stay in the front-end layers.

main.py is Constitution-protected; when these rules change, main.py and
ui/session.py must move together (both import from here, so that happens
mechanically).
"""

CONFIRM_WORDS = ("confirm", "yes", "y")

INTERRUPT_COMMANDS = ("quit", "exit", "stop")


def is_confirm_answer(text: str) -> bool:
    """True iff this is one of the sanctioned approval replies."""
    return (text or "").strip().lower() in CONFIRM_WORDS


def is_interrupt(text: str) -> bool:
    return (text or "").strip().lower() in INTERRUPT_COMMANDS


def plan_summary_text(summary: dict) -> str:
    """One canonical prose form for a finished/paused plan summary —
    shared by _render_plan_summary in both front ends. Byte-identical to
    the historical format (tests + docs reference it)."""
    tasks = summary.get("tasks", [])
    done = [t for t in tasks if t["state"] == "completed"]
    failed = [t for t in tasks if t["state"] == "failed"]

    goal = summary.get("goal", "")
    if summary.get("all_succeeded"):
        return f"Done — completed all {len(done)} step(s) for: {goal}"
    if summary.get("aborted"):
        return (f"Stopped partway through '{goal}' — "
                f"{len(done)} step(s) succeeded, {len(failed)} failed.")
    return (f"Finished '{goal}' with some issues — "
            f"{len(done)} step(s) succeeded, {len(failed)} failed or skipped.")


# ---------------------------------------------------------------------------
# Canonical brain-state vocabulary (evidence layer for ZERION_BRAIN_MAP.md)
# ---------------------------------------------------------------------------
# The runtime's explicit cognitive states and where they are OBSERVED. The UI
# bridge already emits these as core_state events per turn (ui/session.py);
# this mapping is the single reference both docs and tests use. Adding a
# state REQUIRES wiring it somewhere observable first — vocabulary without
# emission is a lie.
BRAIN_STATES = (
    "IDLE", "PERCEIVING", "UNDERSTANDING", "CONTEXTUALIZING", "REMEMBERING",
    "REASONING", "PLANNING", "EXECUTING", "OBSERVING", "CRITICIZING",
    "VERIFYING", "MEMORY-WRITING", "RESPONDING", "LEARNING", "IDLE",
)

# runtime core_state value → canonical state
BRAIN_STATE_MAP = {
    "idle": "IDLE",
    "thinking": "REASONING",           # llm call pending
    "analyzing": "CONTEXTUALIZING",   # context assembly (memory/knowledge/cognition)
    "executing": "EXECUTING",         # tool/agent execution
    "learning": "LEARNING",           # experience capture
    "updating": "MEMORY-WRITING",     # long-term JSON memory write
    "speaking": "RESPONDING",         # answer emitted to user/voice
    "success": "VERIFYING",           # verified finish marker
    "warning": "OBSERVING",           # degraded/partial observation
    "error": "ERROR",
}


def brain_state(core_state: str) -> str:
    return BRAIN_STATE_MAP.get(core_state, core_state.upper())

