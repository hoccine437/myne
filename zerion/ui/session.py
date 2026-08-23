# ui/session.py
"""ZerionUISession — the WebUI adapter for one Zerion conversation.

CRITICAL INVARIANT — pipeline mirroring
---------------------------------------
``process_message`` runs the *same engines in the same order* as
``main.py:run_loop`` handles one line of terminal input:

    interrupt → mute → pending phone approval → pending phone-missing
      → phone extract → command palette → paused-plan confirmation
      → tool confirmation → clarification-question answer
      → memory/knowledge/cognition/capability/runtime context build
      → Intent Engine (+Fast Planner) → AI Planner (gated) → LLM
      → Self-Critic → memory update → learning/capability/runtime
      → intent dispatch (tools, with the Core confirmation flow)

No decision logic lives here beyond what main.py already has; this class
*composes* the existing engines and swaps the I/O surface: instead of
``TerminalUI.write_log`` / ``input()`` / ``speak()``, every effect is
emitted as a structured event on ``ui.events.bus`` for the web client.
Session state and the prompt-memory reducer are *imported from main.py*
(single source of truth), not copied.

Voice synthesis is a presentation concern — the web client speaks replies
with the browser TTS (server-side ``speech.speak`` targets a local audio
player, meaningless for a remote UI), so speak() calls are replaced by
``core_state: speaking`` / ``chat`` events rather than executed here.

If main.py's turn handling ever changes, this file must be updated in
the same pass — the two are intentionally line-comparable.
"""

from __future__ import annotations

import threading
import time

import config
from core import logging as log
from llm import get_llm_output
# Single source of truth for per-session state + prompt-ready memory,
# imported from the Core's own front-end loop rather than duplicated.
from main import SessionMemory, minimal_memory_for_prompt
from knowledge.manager import KnowledgeManager
from learning.engine import LearningEngine
from learning.background import BackgroundLearning
from cognition import CognitiveEngine
from cognition.reasoning import CognitiveReasoningEngine
from capabilities import CapabilityEvolution
from intelligence.runtime import RuntimeIntelligence
from intelligence.critic import self_critic
from phone.engine import PhoneIntelligence
from tools.manager import tool_manager
from planner import planner as planning_engine
from intent import commands as command_palette
from intent.engine import process as classify_and_fast_handle
from intent.models import Intent
from intent.history import action_history
from intent import session_state

from memory.memory_manager import load_memory, update_memory

from core.turn_pipeline import (CONFIRM_WORDS, is_confirm_answer,
                                is_interrupt, plan_summary_text)

from ui.events import bus

# Workspace modes the client knows how to render.
WORKSPACES = {"chat", "coding", "research", "trading", "vision", "automation"}

# Keyword signals for workspace derivation (presentation-only; the Core
# has no notion of "workspaces" — this maps its classification surface
# onto the adaptive layout, the way a view layer should).
_TRADING_MARKERS = (
    "trade", "trading", "stock", "market", "price", "portfolio", "crypto",
    "bitcoin", "chart", "candle", "position", "buy ", "sell ",
)
_VISION_MARKERS = (
    "image", "picture", "photo", "screenshot", "ocr", "detect objects",
    "analyze this image", "what is in this", "vision",
)


# ---------------------------------------------------------------------------
# canonical turn lifecycle wiring (core/turn_runner.TurnRunner owns the
# sequence; this file keeps only the UI-side adapters + the busy/terminal
# channel mechanics that are genuinely front-end concerns)
# ---------------------------------------------------------------------------


class _UiTurnSink:
    """Maps canonical-lifecycle surface calls onto THIS session's existing
    bus events — byte-for-byte the same event shapes the UI already shows."""

    def __init__(self, session: "ZerionUISession"):
        self._s = session
        self._pending_origin = None

    def say(self, text: str, kind: str = "") -> None:
        self._s._say(text, kind=kind)

    def write(self, text: str) -> None:
        self._s._say(text)

    def speak(self, text: str) -> None:
        # the web UI does client-side TTS / token; nothing else to do here
        pass

    def state(self, state: str, detail: str = "") -> None:
        self._s._state(state, detail)

    def stage(self, name, status, detail=None, duration=None) -> None:
        self._s._stage(name, status, detail or {}, duration)

    def decision(self, source: str, text: str) -> None:
        self._s._decision(source, text)

    def notify(self, text: str, level: str = "info") -> None:
        self._s._notify(text, level=level)

    def log(self, level: str, text: str) -> None:
        bus.emit("log", {"level": level, "text": text})

    def confirm_required(self, payload: dict) -> None:
        if payload.get("pending"):
            self._s._set_pending_origin("pipeline")
            bus.emit("confirm_required", {**payload, "source": payload.get("source", "pipeline")})
            self._s._decision("Constitution",
                              "Consequential action is waiting for approval.")
        else:
            bus.emit("confirm_required", {"pending": False})
            self._s._clear_pending_origin()

    def phone_state(self, snap) -> None:
        bus.emit("phone_state", snap)

    def workspace(self, mode: str, source: str, confidence=None) -> None:
        bus.emit("workspace", {"mode": mode, "source": source,
                               "confidence": confidence})

    def focus(self, payload: dict) -> None:
        bus.emit("focus", payload)

    def workflow(self, reason: str) -> None:
        self._s._emit_workflow(reason)

    def goal(self) -> None:
        self._s._emit_goal()

    def agent_row(self, name: str, state: str, detail: str = "") -> None:
        self._s._agent(name, state, detail)

    def tool_event(self, phase: str, tool: str, result, via: str = "",
                   destructive: bool = False, parameters: dict | None = None,
                   message: str = "") -> None:
        payload = {"phase": phase, "tool": tool}
        if result is not None:
            payload["success"] = result.success
            payload["error"] = result.error or ""
            payload.setdefault("output", result.message[:600] if result.message else "")
        if via:
            payload["via"] = via
        if parameters:
            payload["parameters"] = parameters
        if message:
            payload["message"] = message
        bus.emit("tool", payload)

    def memory_update(self, memory_update: dict) -> None:
        bus.emit("memory_update", {"keys": list(memory_update.keys())})

    def no_desktop_actions(self) -> str:
        return ("I can't perform desktop actions in this interface, "
                "but I can still chat and help with information.")

    def on_interrupt_reason(self) -> str:
        return ("Session ended on this device — the Core stays ready. "
                "Reconnect or send another message to resume.")

    def post_classification(self, classification, text: str, cls: dict) -> None:
        workspace = _workspace_for(classification, text)
        if workspace in WORKSPACES:
            bus.emit("workspace", {"mode": workspace, "source": "classification",
                                   "confidence": cls.get("confidence")})
        if classification.intent == Intent.PLANNER or (cls.get("estimated_tool_count") or 0) >= 2:
            bus.emit("focus", {"active": True, "reason": "multi-step task",
                               "task": text[:120]})




def _workspace_for(classification, user_text: str) -> str:  
    """Derive the adaptive-workspace mode from the Core's own
    classification + tool-routing signals. Pure presentation mapping."""
    intent = classification.intent
    lowered = (user_text or "").lower()

    if intent in (Intent.PYTHON, Intent.SHELL):
        return "coding"
    if intent == Intent.PLANNER:
        return "automation"
    if intent == Intent.FILE:
        # File mutation (or anything the classifier marks as execution)
        # is presented as coding work; file reads are research.
        if classification.needs_execution or (classification.matched_tool or "") in (
            "write_file", "move_file", "rename_file", "copy_file", "create_folder",
        ):
            return "coding"
        return "research"
    if intent in (Intent.WEB, Intent.MEMORY):
        return "research"
    if any(m in lowered for m in _TRADING_MARKERS):
        return "trading"
    if any(m in lowered for m in _VISION_MARKERS):
        return "vision"
    return "chat"


class ZerionUISession:
    """One web conversation against the shared Core engine singletons.

    A single instance exists per server process: the Core's planner,
    tool manager and action history are process-level singletons by
    design (one pending-confirmation slot — see tools/manager.py), so
    every connected browser shares this one Core session, exactly as
    multiple terminals attached to one assistant would.
    """

    def __init__(self, speak: bool = False):
        self._speak = speak  # kept for symmetry; the web client does TTS
        self._lock = threading.Lock()  # one turn at a time
        self._busy = False
        self._pending_origin = None    # None | "pipeline" | "terminal"
        # --- same per-session state as main.py (the Core's own class) ---
        self.state = SessionMemory(max_history=config.thinking_history_limit())
        # command_palette/session_state read ``session.pending_intent``
        # directly — expose it as a property (below), never a copy.
        # --- same engine wiring as main.py:run_loop ---
        self.knowledge = KnowledgeManager()
        self.learning = LearningEngine()
        self.capabilities = CapabilityEvolution()
        self.background = BackgroundLearning()
        self.cognition = CognitiveEngine()
        self.reasoning = CognitiveReasoningEngine()
        self.runtime_intelligence = RuntimeIntelligence()
        self.phone = PhoneIntelligence()
        self.pending_phone = None
        self.pending_phone_missing = None
        # engine activity bookkeeping for the System panel
        self._agents = {
            "Intent Engine": {"state": "standby", "detail": "zero-cost classifier", "ts": None},
            "Fast Planner": {"state": "standby", "detail": "local memory/tool shortcuts", "ts": None},
            "AI Planner": {"state": "standby", "detail": "multi-step workflows", "ts": None},
            "Self-Critic": {"state": "standby", "detail": "response review", "ts": None},
            "Learning": {"state": "standby", "detail": "experience capture", "ts": None},
            "Knowledge": {"state": "standby", "detail": "semantic retrieval", "ts": None},
            "Deep Reasoner": {"state": "standby", "detail": "x10 ten-lens deliberation", "ts": None},
            "Runtime Intel": {"state": "standby", "detail": "composition & quality", "ts": None},
            "Tool Manager": {"state": "standby", "detail": "execution + approvals", "ts": None},
            "Constitution": {"state": "standby", "detail": "policy boundary", "ts": None},
            "Agent Orchestrator": {"state": "standby", "detail": "multi-agent task lanes", "ts": None},
        }

    # -- session_state.snapshot compatibility (intent/session_state.py
    # reads session.pending_intent directly) -----------------------------

    @property
    def pending_intent(self):
        return self.state.pending_intent

    # ------------------------------------------------------------------
    # small helpers (event emission is the write_log/speak equivalent)
    # ------------------------------------------------------------------

    @property
    def busy(self) -> bool:
        return self._busy

    def _agent(self, name: str, state: str, detail: str = "") -> None:
        entry = self._agents.get(name)
        if entry is None:
            entry = self._agents[name] = {"state": "standby", "detail": "", "ts": None}
        entry["state"] = state
        if detail:
            entry["detail"] = detail
        entry["ts"] = time.time()
        bus.emit("agents", {"agents": self._agents})

    def _say(self, text: str, kind: str = "") -> None:
        """Assistant-visible message — main.py's ui.write_log(f"AI: ...")."""
        bus.emit("chat", {"role": "ai", "text": text or "", "kind": kind})

    def _stage(self, name: str, status: str, detail: dict = None, duration: float = None) -> None:
        payload = {"stage": name, "status": status}
        if detail:
            payload["detail"] = detail
        if duration is not None:
            payload["duration"] = round(duration, 3)
        bus.emit("stage", payload)

    def _state(self, state: str, detail: str = "") -> None:
        bus.emit("core_state", {"state": state, "detail": detail})

    def _decision(self, source: str, text: str) -> None:
        bus.emit("decision", {"source": source, "text": text})

    def _notify(self, text: str, level: str = "info") -> None:
        bus.emit("notification", {"level": level, "text": text})

    def _emit_workflow(self, reason: str) -> None:
        """Snapshot the planner's current workflow (task states) if one
        exists — the planner executes inside handle_request(), so the UI
        gets a coherent picture at every visible boundary (paused /
        resumed / finished) without needing hooks inside the Core."""
        try:
            workflow = planning_engine.current_workflow()
        except Exception:
            workflow = None
        if workflow is None:
            return
        try:
            tasks = [t.to_dict() for t in workflow.tasks]
        except Exception:
            tasks = []
        status = getattr(getattr(workflow, "status", None), "value",
                         str(getattr(workflow, "status", "")))
        bus.emit("tasks", {
            "goal": workflow.goal,
            "status": status,
            "tasks": tasks,
            "reason": reason,
            "required_tools": list(getattr(workflow, "required_tools", []) or []),
        })

    def _emit_goal(self) -> None:
        try:
            summary = planning_engine.goal_manager.summary()
        except Exception:
            return
        bus.emit("goal", {
            "current_goal": summary.get("current_goal"),
            "sub_goals": summary.get("sub_goals", []),
            "completed": summary.get("completed_count", 0),
            "failed": summary.get("failed_count", 0),
            "queued": summary.get("queued_count", 0),
        })

    # -- main.py equivalents ---------------------------------------------

    def _render_plan_summary(self, summary: dict) -> None:
        """Emit the planner summary in the canonical shared prose
        (core.turn_pipeline.plan_summary_text — single source of truth
        with main.py's own _render_plan_summary)."""
        self._say(plan_summary_text(summary), kind="plan")

    # ------------------------------------------------------------------
    # public entry points (called from the server layer)
    # ------------------------------------------------------------------

    def process_message(self, user_text: str, origin: str = "chat") -> None:
        """Handle exactly one user message, mirroring main.py's loop body.
        Blocking by design — the server runs it in a worker thread."""
        if not user_text or not str(user_text).strip():
            return
        with self._lock:
            if self._busy:
                self._notify("Zerion is busy — still working on the previous message. "
                             "Wait a moment, or say 'cancel' to interrupt a pending action.",
                             level="warning")
                return
            self._busy = True
        bus.emit("turn", {"phase": "start", "origin": origin})
        started = time.monotonic()
        self._state("thinking")
        try:
            self._run_turn(str(user_text), origin)
        except Exception as e:  # the Core is defensive; this is the UI safety net
            log.error(f"ui session turn failed: {e}")
            self._state("error", str(e))
            self._say(f"I ran into an internal error handling that: {e}", kind="error")
            self._notify("A turn failed — see Logs for details.", level="error")
        finally:
            elapsed = time.monotonic() - started
            bus.emit("turn", {"phase": "end", "origin": origin,
                              "seconds": round(elapsed, 3)})
            self._state("idle")
            bus.emit("focus", {"active": False})
            with self._lock:
                self._busy = False

    def confirm(self) -> None:
        """UI confirmation button — identical to typing 'confirm'
        (or approving a terminal-scoped pending call)."""
        with self._lock:
            origin = self._pending_origin
        if origin == "terminal" and tool_manager.has_pending_confirmation():
            self._run_terminal_confirmed()
        else:
            self.process_message("confirm")

    def cancel(self) -> None:
        """UI cancel button — identical to typing anything but 'confirm'."""
        with self._lock:
            origin = self._pending_origin
        if origin == "terminal" and tool_manager.has_pending_confirmation():
            tool_manager.cancel_pending_confirmation()
            with self._lock:
                self._pending_origin = None
            bus.emit("tool", {"phase": "cancelled", "tool": "run_shell"})
            bus.emit("confirm_required", {"pending": False})
        else:
            self.process_message("cancel")

    def idle_tick(self) -> None:
        """Called by the server when no turn has run for a while — the
        web equivalent of main.py's bounded idle-maintenance branch
        (background consolidation + weak-capability visibility)."""
        if self.busy:
            return
        try:
            result = self.background.run_once()
            if result:
                bus.emit("log", {"level": "DEBUG", "text": f"idle maintenance: {result}"})
                self._agent("Learning", "active", "background consolidation")
            weak = self.runtime_intelligence.quality.weak()
            if weak:
                bus.emit("log", {"level": "DEBUG",
                                 "text": f"weak capabilities: {', '.join(weak)}"})
        except Exception as e:
            bus.emit("log", {"level": "WARNING", "text": f"idle maintenance deferred: {e}"})

# ------------------------------------------------------------------
    # the turn — canonical lifecycle delegate (core/turn_runner.py)
    # ------------------------------------------------------------------



    def _run_turn(self, user_text: str, origin: str) -> None:
        """The canonical lifecycle lives in core/turn_runner.py. This method
        wires the session's engines + the UI sink onto it; behavior and event
        order are unchanged (the pipeline tests prove it)."""
        from core.turn_runner import TurnRunner
        if getattr(self, "_turn_runner", None) is None:
            engines = {
                "knowledge": self.knowledge,
                "learning": self.learning,
                "capabilities": self.capabilities,
                "cognition": self.cognition,
                "reasoning": self.reasoning,
                "runtime_intelligence": self.runtime_intelligence,
                "phone": self.phone,
                "tool_manager": tool_manager,
                "planner": planning_engine,
                "command_palette": command_palette,
                "intent_process": classify_and_fast_handle,
                "load_memory": load_memory,
                "update_memory": update_memory,
                "minimal_memory_for_prompt": minimal_memory_for_prompt,
                "llm_call": lambda text, mem: get_llm_output(user_text=text, memory_block=mem),
            }
            self._turn_runner = TurnRunner(
                state=self.state, engines=engines, sink=_UiTurnSink(self),
                pending={"phone": self.pending_phone,
                         "phone_missing": self.pending_phone_missing})
        self._turn_runner.run(user_text)

    def process_image(self, caption: str, image_b64: str, image_mime: str = "image/jpeg",
                      name: str = "image") -> None:
        """Vision turn: an image arrives together with a question — ONE
        brain, same model, same critic, same memory path. Multimodal parts
        flow through the provider chain; never a second engine."""
        if not image_b64:
            return
        with self._lock:
            if self._busy:
                self._notify("Zerion is busy with a task — send the image after it settles.",
                             level="warning")
                return
            self._busy = True
        bus.emit("turn", {"phase": "start", "origin": "vision"})
        started = time.monotonic()
        try:
            bus.emit("chat", {"role": "user", "text": f"📷 {name}" + (f" — {caption}" if caption else ""),
                              "kind": "vision"})
            self._state("analyzing", "reading image")
            bus.emit("workspace", {"mode": "vision", "source": "image"})

            text = (caption or "").strip() or (
                "Analyze this image and say exactly what you see.")
            memory_for_prompt = minimal_memory_for_prompt(load_memory())
            retrieved = self.knowledge.retrieve_context(text, limit=5)
            if retrieved:
                memory_for_prompt["retrieved_knowledge"] = retrieved

            llm_output = get_llm_output(
                user_text=text, memory_block=memory_for_prompt,
                image_b64=image_b64, image_mime=image_mime)
            intent = llm_output.get("intent", "chat")
            response = llm_output.get("text")

            if config.ENABLE_SELF_CRITIC and intent == "chat" and response:
                try:
                    from cognition.reasoning import CognitiveReasoningEngine
                    confidence = CognitiveReasoningEngine().reason(text, []).confidence
                except Exception:
                    confidence = 0.6
                try:
                    critique = self_critic.review(text, response, confidence)
                    if critique.should_improve:
                        response = self_critic.improve(text, response, critique)
                except Exception:
                    pass

            memory_update = llm_output.get("memory_update")
            if memory_update and isinstance(memory_update, dict):
                update_memory(memory_update)
                bus.emit("memory_update", {"keys": list(memory_update.keys())})

            self.state.set_last_user_text(text)
            self.state.set_last_ai_response(response or "")
            if response:
                self._state("speaking")
                self._say(response, kind="vision")
                self._state("success")
            else:
                self._state("error", "empty vision answer")
        except Exception as e:
            log.error(f"vision turn failed: {e}")
            self._state("error", str(e)[:120])
            self._say(f"Vision turn error: {e}", kind="error")
        finally:
            bus.emit("turn", {"phase": "end", "origin": "vision",
                              "seconds": round(time.monotonic() - started, 3)})
            self._state("idle")
            with self._lock:
                self._busy = False

    # ------------------------------------------------------------------
    # intent dispatch — port of main.py's handle_intent
    # ------------------------------------------------------------------

    def _handle_intent(self, intent: str, parameters: dict, response: str) -> None:
        if intent in ("open_app", "send_message"):
            msg = (response or "I can't perform desktop actions in this interface, "
                               "but I can still chat and help with information.")
            self._say(msg)
            self.state.clear_pending_intent()
            return

        tool = tool_manager.get_tool(intent)
        if tool is not None:
            if intent in ("agent_delegate", "agent_orchestrate", "agent_performance"):
                self._agent("Agent Orchestrator", "active", intent)
            self._agent("Tool Manager", "active", intent)
            bus.emit("tool", {"phase": "start", "tool": intent, "parameters": parameters})
            self._state("executing", f"executing {intent}")
            result = tool_manager.execute(intent, parameters)
            if result.error == "confirmation_required":
                bus.emit("tool", {"phase": "confirm", "tool": intent,
                                  "parameters": parameters})
                self._ask_confirmation(result.message, tool=intent, parameters=parameters)
                return
            bus.emit("tool", {"phase": "end", "tool": intent,
                              "success": result.success, "error": result.error or ""})
            msg = result.message or (response or "")
            self._say(msg, kind="tool")
            self._state("success" if result.success else "error",
                        "" if result.success else (result.error or "tool failed"))
            return

        # weather_report, search, and any other intent with no matching
        # tool: use the model's own text response directly, as in main.py.
        if response:
            self._say(response)

    # ------------------------------------------------------------------
    # terminal channel (drives the Terminal panel through run_shell)
    # ------------------------------------------------------------------

    def run_terminal_command(self, command: str) -> None:
        """Execute a shell command *through the Tool Manager* — including
        its Constitution policy check and destructive-confirmation flow.
        Nothing here bypasses or re-implements the Core."""
        command = (command or "").strip()
        if not command:
            return
        if self.busy:
            self._notify("Zerion is busy — wait for the current turn to finish.",
                         level="warning")
            bus.emit("tool", {"phase": "rejected", "tool": "run_shell",
                              "reason": "busy", "command": command})
            return

        def _run():
            self._agent("Tool Manager", "active", "terminal: run_shell")
            bus.emit("tool", {"phase": "start", "tool": "run_shell",
                              "parameters": {"command": command}, "channel": "terminal"})
            result = tool_manager.execute("run_shell", {"command": command})
            if result.error == "confirmation_required":
                self._set_pending_origin("terminal")
                bus.emit("confirm_required", {
                    "pending": True, "source": "terminal", "tool": "run_shell",
                    "command": command, "message": result.message,
                })
                bus.emit("tool", {"phase": "confirm", "tool": "run_shell",
                                  "command": command, "message": result.message})
                return
            bus.emit("tool", {"phase": "end", "tool": "run_shell",
                              "channel": "terminal", "success": result.success,
                              "output": result.message, "error": result.error or ""})

        threading.Thread(target=_run, daemon=True).start()

    def _run_terminal_confirmed(self) -> None:
        result = tool_manager.confirm_pending()
        self._clear_pending_origin()
        bus.emit("confirm_required", {"pending": False})
        bus.emit("tool", {"phase": "end", "tool": "run_shell", "channel": "terminal",
                          "success": result.success, "output": result.message,
                          "error": result.error or ""})

    # ------------------------------------------------------------------
    # shared helpers
    # ------------------------------------------------------------------

    def _ask_confirmation(self, message: str, tool: str = "", parameters: dict = None) -> None:
        self._set_pending_origin("pipeline")
        bus.emit("confirm_required", {
            "pending": True, "source": "pipeline", "tool": tool,
            "parameters": parameters or {}, "message": message,
        })
        self._say(message, kind="confirm")
        self._decision("Constitution", "Consequential action is waiting for approval.")

    def _set_pending_origin(self, origin: str) -> None:
        with self._lock:
            self._pending_origin = origin

    def _clear_pending_origin(self) -> None:
        with self._lock:
            self._pending_origin = None

    def snapshot(self) -> dict:
        """Read-only view of session + planner + tool + history state,
        via the Core's own intent/session_state.py (no duplication)."""
        return session_state.snapshot(self, tool_manager, planning_engine, action_history)
