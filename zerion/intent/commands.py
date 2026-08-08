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
from intent import multilingual

COMMANDS = {
    "/status", "/tools", "/memory", "/history", "/goals",
    "/plugins", "/debug", "/help", "/plan", "/serious", "/normal",
    "/benchmark", "/learn",
}

# ---------------------------------------------------------------------------
# privileged interactive states (module-scope: one pending slot per process,
# same discipline as tool_manager's single confirmation slot)
# ---------------------------------------------------------------------------
_AUTH_PENDING = False      # serious-mode challenge is waiting for a code
_FLOW_PENDING = None       # {"platform":..., "scope":..., "expires_at": ts}
_FLOW_PENDING_TTL = 60.0


def pending_secret_input() -> bool:
    """True while an authentication challenge awaits the user's code. The UI
    masks the user-side echo in this state (the attempt is never emitted to
    the event stream, replay buffer, or any log)."""
    return _AUTH_PENDING


def _flow_pending_live():
    global _FLOW_PENDING
    import time as _t
    if _FLOW_PENDING and _t.time() < _FLOW_PENDING.get("expires_at", 0):
        return _FLOW_PENDING
    _FLOW_PENDING = None
    return None

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
    # privileged pending states consume ANY next input locally (auth codes
    # and flow confirmations must never fall through to the LLM path)
    if _AUTH_PENDING or _flow_pending_live() is not None:
        return True
    if stripped.lower() in _PHRASE_COMMANDS:
        return True
    first_word = stripped.lower().split()[0]
    if first_word in COMMANDS:
        return True
    # multilingual semantic layer (intent-based, language-independent):
    # only fires when the evidence is coherent (topic+action); otherwise
    # the request proceeds to the normal pipeline untouched
    return multilingual.match(stripped) is not None


def handle(user_text: str, session, memory: dict) -> str:
    """Execute a slash command and return the text to display. Assumes
    is_command(user_text) was already True."""
    stripped = user_text.strip()
    lowered_full = stripped.lower()

    # -- privileged pending interceptions: auth code / flow confirmation ---
    #    these check first so secret material and scoped confirmations never
    #    flow to any downstream stage (LLM, planner, memory, logs)
    global _AUTH_PENDING, _FLOW_PENDING
    if _AUTH_PENDING:
        # de-escalation during a challenge is always free: cancel/disable
        # words abort the prompt instead of being consumed as an attempt
        cancel_mark = multilingual.match(stripped)
        if lowered_full in ("cancel", "nevermind", "never mind", "لا", "بطال") or \
           (cancel_mark and cancel_mark["intent"] == "DISABLE_SERIOUS_MODE"):
            _AUTH_PENDING = False
            return "Serious Mode activation cancelled."
        _AUTH_PENDING = False
        reply = _auth_attempt(stripped)
        return reply
    pending = _flow_pending_live()
    if pending is not None:
        from core.turn_pipeline import is_confirm_answer
        platform = pending["platform"]
        _FLOW_PENDING = None
        if is_confirm_answer(stripped):
            from comms import bgworkflows
            import config as _cfg
            flow = bgworkflows.start(platform, scope="messages",
                                     ttl_s=_cfg.COMM_FLOW_TTL)
            return (f"Background workflow ACTIVE [{flow['flow_id']}]: {platform} "
                    f"messages — drafts+low-risk replies under the full safety gate. "
                    f"Expires in {_cfg.COMM_FLOW_TTL // 3600}h. "
                    f"Stop anytime with 'stop {platform}' or the panel.")
        return f"Cancelled — no {platform} workflow was started."

    if lowered_full in _PHRASE_COMMANDS:
        cmd = _PHRASE_COMMANDS[lowered_full]
    else:
        cmd = ""
    parts = stripped.split()
    cmd = cmd or parts[0].lower()

    if cmd == "/serious":
        return _serious_on()

    if cmd == "/normal":
        import personality
        return personality.set_mode(personality.NORMAL)

    # -- multilingual semantic intents (matched as commands by is_command) --
    m = multilingual.match(stripped)
    if m:
        intent = m["intent"]
        if intent == "ENABLE_SERIOUS_MODE":
            return _serious_on()
        if intent == "DISABLE_SERIOUS_MODE":
            import personality
            if personality.serious_active():
                return personality.set_mode(personality.NORMAL)
            return "Serious Mode is not active."
        if intent == "START_COMM_FLOW":
            return _flow_start_stage(m["platform"])
        if intent == "STOP_COMM_FLOW":
            return _flow_stop(m.get("platform", ""))
        if intent == "ESTOP_ALL":
            # safe-direction op: immediate, no confirmation needed
            from comms import overrides
            out = overrides.estop("user command (stop all communication)")
            return (f"All external communication stopped. "
                    f"{out.get('queue_dropped', 0)} queued item(s) dropped. "
                    f"Say 'resume communication' or /use comm_resume to heal.")
        if intent == "RESUME_COMM":
            # resuming outbound authority needs the confirmation-gated path —
            # route through the same tool the LLM would use
            result = tool_manager.execute("comm_resume", {})
            return result.message

    if cmd == "/help":
        return (
            "Commands: /status /tools /memory /history /goals /plugins "
            "/debug [on|off] /plan /learn <topic> /help"
        )

    if cmd == "/learn":
        # Explicit, bounded self-teaching through the SAME canonical path
        # the LLM uses (learning tool → LearningController) — no duplicate
        # loop here, and identical in both front ends. Fully local.
        topic = stripped[len("/learn"):].strip()
        if len(topic) < 3:
            return "Usage: /learn <topic> — runs one bounded self-teaching loop (local, offline)."
        result = tool_manager.execute("learn_domain", {"topic": topic})
        return result.message

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

    if cmd == "/benchmark":
        # live capability checks; both entry points share this local command
        import benchmarks
        report = benchmarks.run_all()
        parts2 = []
        for lens, sub in report["results"].items():
            quality = ",".join(f"{k}={v}" for k, v in sub.items()
                               if not k.endswith("_ms") and not isinstance(v, (list, dict)))
            parts2.append(f"{lens}: {quality or 'ok'}")
        parts2.append(f"overall: {'OK' if report['all_ok'] else 'DEGRADED'} in {report['total_latency_s']}s")
        return "\n".join(parts2)

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


# ---------------------------------------------------------------------------
# privileged command implementations (serious mode auth, comm flows)
# ---------------------------------------------------------------------------

def _serious_on() -> str:
    """ENABLE_SERIOUS_MODE — the challenge is the gate; the code is the proof."""
    global _AUTH_PENDING
    import personality
    if personality.serious_active():
        return "Serious Mode is already ON."
    from security import serious_auth
    state = serious_auth.attempts_state()
    if state["locked"]:
        return (f"Serious Mode authentication is locked for "
                f"{state['lock_remaining_s']}s. Try later.")
    _AUTH_PENDING = True
    return ("Serious Mode requires authentication.\n"
            "Please enter your password. (It is never stored, shown, "
            "logged, or sent anywhere.)")


def _auth_attempt(text: str) -> str:
    """Verify the transient attempt. The raw text never leaves this call."""
    from security import serious_auth
    import personality
    from core import logging as log
    result = serious_auth.verify(text)
    del text
    if result["ok"]:
        ack = personality.set_mode(personality.SERIOUS)
        try:
            from comms import audit
            audit.record("serious_mode", platform="core", result="activated")
        except Exception:
            pass
        log.info("serious mode activated (authenticated)")
        return ("SERIOUS MODE: ON — direct task discipline active.\n"
                "Verification-first responses; all constitutional and safety "
                "boundaries remain fully enforced.")
    try:
        from comms import audit
        audit.record("serious_mode", platform="core", result="auth_failed")
    except Exception:
        pass
    log.warning("serious mode authentication failed (attempt not recorded)")
    if result["locked_for"]:
        return (f"Authentication failed too many times — Serious Mode stays "
                f"OFF and retries are locked for {result['locked_for']}s.")
    return "Authentication failed. Serious Mode remains disabled."


def _flow_start_stage(platform: str) -> str:
    global _FLOW_PENDING
    import config as _cfg
    import time as _t
    from comms.registry import connectors
    conn = connectors.get(platform) or (
        connectors.get("phone") if platform in ("social", "phone") else None)
    connector_note = ""
    try:
        state = (conn.health() if conn else {}).get("state", "disconnected")
        connector_note = f" Connector '{platform}': {state}."
        if state == "disconnected":
            connector_note += (" (no live platform bridge detected — the flow "
                               "will observe + draft and use supervised deep "
                               "link handoff where supported.)")
    except Exception:
        pass
    _FLOW_PENDING = {"platform": platform,
                     "expires_at": _t.time() + _FLOW_PENDING_TTL}
    return (f"Understood: background communication workflow for "
            f"'{platform}' — scope: incoming messages; allowed: draft + "
            f"low-risk replies (full safety gates stay on; high-risk always "
            f"asks). Expires after {_cfg.COMM_FLOW_TTL // 3600}h or on "
            f"'stop {platform}'.{connector_note}\n"
            f"Reply 'confirm' to activate.")


def _flow_stop(platform: str) -> str:
    from comms import bgworkflows
    n = bgworkflows.stop(platform=platform)
    if not platform:
        return "Which background workflow should stop? Say e.g. 'stop instagram'."
    return (f"Stopped {n} active {platform} workflow(s). No background "
            f"replies will be drafted or sent for it anymore."
            if n else
            f"No active {platform} background workflow was running.")
