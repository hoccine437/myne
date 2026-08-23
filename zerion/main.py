# main.py
"""Mark-X Lite — Zerion's official production entry point.

Since the final release the Web UI is the default front end:
`python main.py` boots the adaptive browser workspace (and can also run
under `python -m runtime` for 24/7 service mode). A minimal built-in
legacy REPL remains for UI-less hosts (`--terminal`), or when the UI
extras are not installed.

Same conversation loop, memory handling, and intent contract as the
original Mark-X, minus the GUI and desktop-automation layers that don't
belong on Termux / low-resource Linux.
"""

import config
import os
import sys
import threading
import time
from core import logging as log
from llm import get_llm_output
from knowledge.manager import KnowledgeManager
from learning.engine import LearningEngine
from learning.background import BackgroundLearning
from cognition import CognitiveEngine
from cognition.reasoning import CognitiveReasoningEngine
from capabilities import CapabilityEvolution
from constitution.constitution import ConstitutionEngine
from intelligence.runtime import RuntimeIntelligence
from intelligence.critic import self_critic
from phone.engine import PhoneIntelligence
from speech import speak, speech_status
from tools.manager import tool_manager
from planner import planner as planning_engine
from intent import commands as command_palette
from intent.engine import process as classify_and_fast_handle
from intent.models import Intent

from memory.memory_manager import load_memory, update_memory

from core.turn_pipeline import (INTERRUPT_COMMANDS, is_confirm_answer,
                                plan_summary_text)


class SessionMemory:
    """Lightweight in-memory session state: pending intents, parameters,
    and a short rolling conversation history for follow-up questions."""

    def __init__(self, max_history: int = 5):
        self.max_history = max_history
        self.reset()

    def reset(self):
        self.pending_intent = None
        self.parameters = {}
        self.current_question = None
        self.last_user_text = None
        self.last_ai_response = None
        self.conversation_history = []

    def set_pending_intent(self, intent):
        self.pending_intent = intent

    def clear_pending_intent(self):
        self.pending_intent = None
        self.parameters = {}
        self.current_question = None

    def has_pending_intent(self) -> bool:
        return self.pending_intent is not None

    def update_parameters(self, new_params: dict):
        if not isinstance(new_params, dict):
            return
        for k, v in new_params.items():
            if v not in (None, ""):
                self.parameters[k] = v

    def get_parameters(self) -> dict:
        return self.parameters.copy()

    def get_parameter(self, key):
        return self.parameters.get(key)

    def set_current_question(self, param_name):
        self.current_question = param_name

    def get_current_question(self):
        return self.current_question

    def clear_current_question(self):
        self.current_question = None

    def set_last_user_text(self, text):
        self.last_user_text = text
        self._add_to_history("user", text)

    def set_last_ai_response(self, text):
        self.last_ai_response = text
        self._add_to_history("ai", text)

    def get_last_user_text(self):
        return self.last_user_text

    def _add_to_history(self, role, text):
        if role not in ("user", "ai") or not text:
            return
        self.conversation_history.append({"role": role, "text": text})
        if len(self.conversation_history) > self.max_history:
            self.conversation_history.pop(0)

    def get_history_for_prompt(self) -> str:
        return "\n".join(
            f"{m['role'].capitalize()}: {m['text']}"
            for m in self.conversation_history
        )


def minimal_memory_for_prompt(memory: dict) -> dict:
    """Reduce long-term memory to the small set of fields worth sending to
    the LLM on every turn (keeps prompts cheap and fast)."""
    result = {}
    identity = memory.get("identity", {})
    preferences = memory.get("preferences", {})
    relationships = memory.get("relationships", {})
    emotional_state = memory.get("emotional_state", {})

    if "name" in identity:
        result["user_name"] = identity["name"].get("value")

    for k in ["favorite_color", "favorite_food", "favorite_music"]:
        if k in preferences:
            val = preferences[k].get("value")
            if isinstance(val, dict) and "value" in val:
                val = val["value"]
            result[k] = val

    for rel, info in relationships.items():
        if isinstance(info, dict) and "name" in info and "value" in info["name"]:
            result[f"{rel}_name"] = info["name"]["value"]

    for event, info in emotional_state.items():
        if isinstance(info, dict) and "value" in info:
            result[f"emotion_{event}"] = info["value"]

    return {k: v for k, v in result.items() if v}


def _render_plan_summary(summary: dict, ui):
    """Turn a planner execution summary into a short spoken/printed
    report — which steps ran, which failed, overall outcome. The prose
    itself is owned by core.turn_pipeline (shared with the UI front end)."""
    msg = plan_summary_text(summary)
    ui.write_log(f"AI: {msg}")
    speak(msg)


def handle_intent(intent: str, parameters: dict, response: str, ui, session: SessionMemory):
    """
    Dispatch non-chat intents. Legacy GUI-era intents (open_app,
    send_message) are still acknowledged but not executed, exactly as
    before. Any other non-chat intent is looked up in the Tool Manager —
    if a matching tool exists, it runs (or asks for confirmation, for
    destructive tools); if not, the model's own text response is used.
    """
    if intent in ("open_app", "send_message"):
        msg = (response or "I can't perform desktop actions in Mark-X Lite, "
                            "but I can still chat and help with information.")
        ui.write_log(f"AI: {msg}")
        speak(msg)
        session.clear_pending_intent()
        return

    tool = tool_manager.get_tool(intent)
    if tool is not None:
        result = tool_manager.execute(intent, parameters)
        if result.error == "confirmation_required":
            ui.write_log(f"AI: {result.message}")
            speak(result.message)
            return
        msg = result.message or (response or "")
        ui.write_log(f"AI: {msg}")
        speak(msg)
        return

    # weather_report, search, and any other intent with no matching tool:
    # use the model's own text response directly, same as before.
    if response:
        ui.write_log(f"AI: {response}")
        speak(response)


class _TerminalSink(object):
    """Canonical-lifecycle surface for the built-in terminal front end.
    Behavior-by-design: writes+speaks the assistant lines exactly as the
    legacy loop did; structural telemetry (stages/decision rows/tool phasing)
    is a UI concern and stays silent here (the same as it always was)."""

    def __init__(self, ui):
        self._ui = ui

    def say(self, text: str, kind: str = "") -> None:
        self._ui.write_log(f"AI: {text}")
        # legacy terminal spoke assistant lines; palette/tool replies stay spoken too
        if kind != "command":
            speak(text or "")

    def write(self, text: str) -> None:
        self._ui.write_log(text)

    def speak(self, text: str) -> None:
        speak(text or "")

    def state(self, state: str, detail: str = "") -> None:
        if state == "thinking":
            self._ui.start_speaking()
        elif state in ("speaking", "success", "error", "idle"):
            self._ui.stop_speaking()

    def stage(self, name, status, detail=None, duration=None) -> None:
        pass

    def decision(self, source: str, text: str) -> None:
        log.debug(f"decision[{source}]: {text}")

    def notify(self, text: str, level: str = "info") -> None:
        # legacy terminal stayed silent for bookkeeping notices
        pass

    def log(self, level: str, text: str) -> None:
        # legacy loop printed parenthesized notices — keep that exact shape
        message = text if str(text).startswith("(") else f"({text})"
        print(message)

    def confirm_required(self, payload: dict) -> None:
        pass  # terminal confirmation is next-input based, as it always was

    def phone_state(self, snap) -> None:
        pass

    def workspace(self, mode: str, source: str, confidence=None) -> None:
        pass

    def focus(self, payload: dict) -> None:
        pass

    def workflow(self, reason: str) -> None:
        pass

    def goal(self) -> None:
        pass

    def agent_row(self, name: str, state: str, detail: str = "") -> None:
        pass

    def tool_event(self, phase: str, tool: str, result, **kw) -> None:
        pass

    def memory_update(self, memory_update: dict) -> None:
        pass

    def post_classification(self, classification, text: str, cls: dict) -> None:
        pass

    def no_desktop_actions(self) -> str:
        return ("I can't perform desktop actions in Mark-X Lite, "
                "but I can still chat and help with information.")

    def on_interrupt_reason(self) -> str:
        return ""   # terminal prints its own "Goodbye." at loop break


def run_loop(ui):
    # Think-x10 keeps a larger bounded conversational window; THINKING_MODE=off
    # restores the configured lightweight MAX_HISTORY window.
    session = SessionMemory(max_history=config.thinking_history_limit())
    # same engine set as before — identical instances, identical behavior
    knowledge = KnowledgeManager()
    learning = LearningEngine()
    capabilities = CapabilityEvolution()
    background = BackgroundLearning()
    cognition = CognitiveEngine()
    reasoning = CognitiveReasoningEngine()
    runtime_intelligence = RuntimeIntelligence()
    phone = PhoneIntelligence()

    print("Mark-X Lite — type 'exit' to quit.")
    print(speech_status())

    from core.turn_runner import TurnRunner
    engines = {
        "knowledge": knowledge, "learning": learning, "capabilities": capabilities,
        "cognition": cognition, "reasoning": reasoning,
        "runtime_intelligence": runtime_intelligence, "phone": phone,
        "tool_manager": tool_manager, "planner": planning_engine,
        "command_palette": command_palette,
        "intent_process": classify_and_fast_handle,
        "load_memory": load_memory, "update_memory": update_memory,
        "minimal_memory_for_prompt": minimal_memory_for_prompt,
        "llm_call": lambda text, mem: get_llm_output(user_text=text,
                                                     memory_block=mem),
    }
    runner = TurnRunner(session, engines, _TerminalSink(ui))

    while True:
        user_text = ui.get_input()

        if not user_text or not user_text.strip():
            # idle work is bounded and load-aware — unchanged legacy behavior
            maintenance_result = background.run_once()
            if maintenance_result:
                log.debug(f"idle maintenance: {maintenance_result}")
            weak = runtime_intelligence.quality.weak()
            if weak:
                log.debug(f"idle maintenance: weak capabilities: {', '.join(weak)}")
            continue

        outcome = runner.run(user_text)
        if outcome == "exit":
            print("Goodbye.")
            break


# ---------------------------------------------------------------------------
# Entry point — UI-first
# ---------------------------------------------------------------------------

class _UIUnavailable(RuntimeError):
    pass


class _MinimalTerminalUI:
    """Inline legacy adapter (terminal.py was retired). The full terminal
    persona is gone; this is a functional stdin/stdout surface for hosts
    without the UI extras. All Core behavior still flows through run_loop
    unchanged."""

    def write_log(self, text: str) -> None:
        print(text)

    def start_speaking(self) -> None:
        pass

    def stop_speaking(self) -> None:
        pass

    def get_input(self, prompt: str = "You: ") -> str:
        try:
            return input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            return "exit"


def _run_legacy_terminal() -> None:
    print("Mark-X Lite (legacy terminal) — type 'exit' to quit.")
    print(speech_status())
    # Ready announcement: constitution loaded + config validated already —
    # deliver the startup greeting exactly once (voice when available,
    # text otherwise). The Web UI path greets from ui.server's lifespan
    # hook instead; the once-guard prevents doubles either way.
    try:
        from runtime import greeting
        greeting.deliver_startup_greeting(memory=load_memory(), text_channel=print,
                                          blocking=False)
    except Exception:
        pass
    ui = _MinimalTerminalUI()
    try:
        run_loop(ui)
    except KeyboardInterrupt:
        print("\nGoodbye.")


def _arg_value(args: list, flag: str) -> str:
    try:
        i = args.index(flag)
        return args[i + 1]
    except (ValueError, IndexError):
        return ""


def _maybe_open_browser(port: int) -> None:
    """Best-effort auto-open of the UI after the server is up. Never blocks
    startup; silent on headless hosts."""
    import threading
    import webbrowser

    host_is_public = os.environ.get("ZERION_UI_PUBLIC", "").strip().lower() in ("1", "true", "yes", "on")
    url = f"http://127.0.0.1:{port}/" if not host_is_public else f"http://localhost:{port}/"

    def _open():
        time.sleep(1.2)  # let uvicorn bind first
        try:
            if os.environ.get("PREFIX", "").find("com.termux") >= 0:
                import shutil
                import subprocess
                if shutil.which("termux-open-url"):
                    subprocess.run(["termux-open-url", url], timeout=5,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            if sys.stdout.isatty() or os.environ.get("DISPLAY"):
                webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=_open, name="zerion-browser-open", daemon=True).start()


def _run_ui(args) -> None:
    host = _arg_value(args, "--host") or os.getenv("ZERION_UI_HOST", "0.0.0.0")
    port_raw = _arg_value(args, "--port") or os.getenv("ZERION_UI_PORT", "8765")
    try:
        port = int(port_raw)
    except ValueError:
        print(f"[startup] invalid --port {port_raw!r}; using 8765")
        port = 8765
    try:
        import uvicorn
        import ui.server as ui_server
    except ImportError as exc:
        raise _UIUnavailable(
            "Web UI extras are not installed "
            f"({exc.name or exc}). Install with: pip install -r ui/requirements-ui.txt — "
            "or use `python main.py --terminal` for the minimal built-in REPL.")

    print(f"Zerion UI — {ui_server._bootstrap_payload()['name']} "
          f"v{ui_server._bootstrap_payload()['version']}")
    print(f"Serving on http://{host}:{port}  (Ctrl+C to stop)")
    if not os.environ.get("ZERION_UI_NO_AUTOOPEN"):
        _maybe_open_browser(port)

    # uvicorn's stock run() only handles SIGINT; map SIGTERM to the same
    # graceful should_exit path so service managers / `pkill` stop us cleanly.
    uconfig = uvicorn.Config(ui_server.app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(uconfig)
    import signal as _signal

    def _graceful(signum, frame):
        server.should_exit = True

    if threading.current_thread() is threading.main_thread():
        _signal.signal(_signal.SIGTERM, _graceful)
        _signal.signal(_signal.SIGINT, _graceful)
    server.run()


def main():
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print("Usage: python main.py [--host H] [--port P] [--terminal]")
        print("  default       start the Web UI (adaptive workspace)")
        print("  --terminal    built-in minimal REPL (no UI extras needed)")
        return

    # Load and integrity-check once at startup; all normal requests reuse cache.
    from core.bootstrap import bootstrap
    _boot_report = bootstrap("terminal" if "--terminal" in args else "ui")
    for warning in _boot_report.get("config_warnings") or []:
        print(f"[configuration] {warning}")

    if "--terminal" in args or "--legacy" in args:
        _run_legacy_terminal()
        return

    try:
        _run_ui(args)
    except _UIUnavailable as e:
        print(str(e))
        _run_legacy_terminal()
    except KeyboardInterrupt:
        print("\nGoodbye.")


if __name__ == "__main__":
    main()
