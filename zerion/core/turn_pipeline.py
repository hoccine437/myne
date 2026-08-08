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
