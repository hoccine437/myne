# intent/commands.py
"""
Command Palette: slash commands that are handled entirely locally, never
passing through the LLM. Recognized here before classification even runs
(main.py checks this first), so these always work even with no API key
configured and no network available.

/plugins is intentionally NOT implemented -- there is no plugin system
yet (see tools/README.md's "future expansion" note: a second parallel
auto-discovery mechanism alongside tools/ would duplicate that logic
with no clear boundary between "tool" and "plugin"). /plugins currently
reports that tools/ already serves this role.
"""

from intent import session_state
from planner import planner as planning_engine
from tools.manager import tool_manager
from intent.history import action_history

COMMANDS = {
    "/status", "/tools", "/memory", "/history", "/goals",
    "/plugins", "/debug", "/help", "/plan", "/serious", "/normal",
}

# Persona switches also accept the natural-language (exact-phrase) forms —
# exact matches only, so genuine requests that merely start with "start…"
# still flow to the normal pipeline untouched.
_PHRASE_COMMANDS = {
    "start serious mode": "/serious",
    "stop serious mode": "/normal",
    "end serious mode": "/normal",
    "start normal mode": "/normal",
    "serious mode on": "/serious",
    "serious mode off": "/normal",
}


def is_command(user_text: str) -> bool:
    stripped = (user_text or "").strip()
    if not stripped:
        return False
    if stripped.lower() in _PHRASE_COMMANDS:
        return True
    first_word = stripped.lower().split()[0]
    return first_word in COMMANDS


def handle(user_text: str, session, memory: dict) -> str:
    """Execute a slash command and return the text to display. Assumes
    is_command(user_text) was already True."""
    stripped = user_text.strip()
    lowered_full = stripped.lower()
    if lowered_full in _PHRASE_COMMANDS:
        cmd = _PHRASE_COMMANDS[lowered_full]
    else:
        cmd = ""
    parts = stripped.split()
    cmd = cmd or parts[0].lower()

    if cmd == "/serious":
        import personality
        return personality.set_mode(personality.SERIOUS)

    if cmd == "/normal":
        import personality
        return personality.set_mode(personality.NORMAL)

    if cmd == "/help":
        return (
            "Commands: /status /tools /memory /history /goals /plugins "
            "/debug [on|off] /plan /help"
        )

    if cmd == "/status":
        snap = session_state.snapshot(session, tool_manager, planning_engine, action_history)
        lines = [
            f"Current goal: {snap['current_goal'] or 'none'}",
            f"Completed goals this session: {snap['completed_goals']}",
            f"Failed goals this session: {snap['failed_goals']}",
            f"Pending confirmation: {'yes' if (snap['pending_tool_confirmation'] or snap['pending_plan_confirmation']) else 'no'}",
            f"Actions run: {snap['action_totals']['total_actions']} "
            f"({snap['action_totals']['succeeded']} succeeded, {snap['action_totals']['failed']} failed)",
        ]
        return "\n".join(lines)

    if cmd == "/tools":
        tools = tool_manager.list_tools()
        if not tools:
            return "No tools currently available."
        return "\n".join(f"- {t['name']}: {t['description']}" for t in tools)

    if cmd == "/memory":
        if not memory:
            return "No memory stored yet."
        return "\n".join(f"{k}: {v}" for k, v in memory.items())

    if cmd == "/history":
        entries = action_history.recent(limit=10)
        if not entries:
            return "No actions run yet this session."
        lines = []
        for e in entries:
            status = "ok" if e["success"] else f"failed ({e['reason']})"
            lines.append(f"- {e['tool']}: {status}, {e['duration_seconds']}s")
        return "\n".join(lines)

    if cmd == "/goals":
        summary = planning_engine.goal_manager.summary()
        return (
            f"Current: {summary['current_goal'] or 'none'}\n"
            f"Completed: {summary['completed_count']}, Failed: {summary['failed_count']}, "
            f"Queued: {summary['queued_count']}"
        )

    if cmd == "/plugins":
        return ("No separate plugin system yet -- tools/ already provides drop-in, "
                "auto-discovered capabilities. See tools/README.md.")

    if cmd == "/debug":
        arg = parts[1].lower() if len(parts) > 1 else None
        if arg == "on":
            planning_engine.set_debug(True)
            return "Debug mode on."
        if arg == "off":
            planning_engine.set_debug(False)
            return "Debug mode off."
        return f"Debug mode is currently {'on' if planning_engine.DEBUG else 'off'}. Use /debug on|off."

    if cmd == "/plan":
        workflow = planning_engine.current_workflow()
        if workflow is None:
            return "No active plan right now."
        lines = [
            f"Active workflow: {workflow.goal}",
            f"Status: {workflow.status.value}",
            f"Required tools: {', '.join(workflow.required_tools) or 'none'}",
        ]
        lines += [f"- [{t.state.value}] {t.description}" for t in workflow.tasks]
        return "\n".join(lines)

    return "Unknown command. Try /help."
