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
        self.state = SessionMemory(max_history=config.MAX_HISTORY)
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
            "Runtime Intel": {"state": "standby", "detail": "composition & quality", "ts": None},
            "Tool Manager": {"state": "standby", "detail": "execution + approvals", "ts": None},
            "Constitution": {"state": "standby", "detail": "policy boundary", "ts": None},
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
    # the turn — mirrors main.py:run_loop branch-for-branch
    # ------------------------------------------------------------------

    def _run_turn(self, user_text: str, origin: str) -> None:
        text = user_text.strip()
        lowered = text.lower()
        session = self.state

        bus.emit("chat", {"role": "user", "text": text, "kind": origin})

        # --- interrupt words: the web equivalent of quitting the loop ---
        if is_interrupt(lowered):
            self._say("Session ended on this device — the Core stays ready. "
                      "Reconnect or send another message to resume.")
            return

        # --- mute: reset session ---------------------------------------
        if lowered == "mute":
            session.reset()
            self._decision("Session", "Session context cleared (mute).")
            self._say("Context cleared. Fresh session.")
            return

        # --- pending phone approval ------------------------------------
        if self.pending_phone is not None:
            if is_confirm_answer(lowered):
                goal, intent = self.pending_phone
                self._agent("Tool Manager", "active", "phone dispatch (approved)")
                result = self.phone.dispatcher.dispatch(goal, intent, approved=True)
                self._say(result.message)
            else:
                self._say("Cancelled — no phone action was performed.")
            self.pending_phone = None
            return

        # --- pending phone-missing-info --------------------------------
        if self.pending_phone_missing is not None:
            goal_text, extracted_phone = self.pending_phone_missing
            retry_text = f"{goal_text} {text}".strip()
            extracted_phone = self.phone.extractor.extract(retry_text) or extracted_phone
            if extracted_phone.missing:
                self._say("Still missing: " + ", ".join(extracted_phone.missing)
                          + ". Reply with that, or say 'cancel'.")
                if lowered == "cancel":
                    self.pending_phone_missing = None
                    self._say("Cancelled.")
                else:
                    self.pending_phone_missing = (goal_text, extracted_phone)
                return
            self.pending_phone_missing = None
            result = self.phone.dispatcher.dispatch(retry_text, extracted_phone, approved=False)
            if "Approval required" in result.message:
                self.pending_phone = (retry_text, extracted_phone)
                self._ask_confirmation(result.message + " Reply 'confirm' to proceed.")
            else:
                self._say(result.message)
            return

        # --- fresh phone intent ----------------------------------------
        extracted_phone = self.phone.extractor.extract(text)
        if extracted_phone is not None:
            self._agent("Tool Manager", "active", "phone intent")
            if extracted_phone.missing:
                self.pending_phone_missing = (text, extracted_phone)
                self._say("Missing required information: " + ", ".join(extracted_phone.missing) + ".")
                return
            result = self.phone.dispatcher.dispatch(text, extracted_phone, approved=False)
            if "Approval required" in result.message:
                self.pending_phone = (text, extracted_phone)
                self._ask_confirmation(result.message + " Reply 'confirm' to proceed.")
            else:
                self._say(result.message)
            return

        # --- command palette: fully local, unchanged --------------------
        if command_palette.is_command(text):
            self._agent("Intent Engine", "active", "command palette")
            memory_snapshot = minimal_memory_for_prompt(load_memory())
            output = command_palette.handle(text, session, memory_snapshot)
            self._say(output, kind="command")
            self._emit_goal()
            return

        # --- paused-plan confirmation (before single-tool confirmation)--
        if planning_engine.has_paused_plan():
            self._agent("AI Planner", "active", "paused plan decision")
            if is_confirm_answer(lowered):
                pending_tool_result = None
                if tool_manager.has_pending_confirmation():
                    pending_tool_result = tool_manager.confirm_pending()
                bus.emit("confirm_required", {"pending": False})
                self._clear_pending_origin()
                if pending_tool_result is None:
                    self._say("Nothing to confirm right now.")
                    return
                self._emit_workflow("resumed")
                outcome = planning_engine.resume_paused_plan(pending_tool_result)
                if outcome.get("paused"):
                    self._emit_workflow("paused")
                    self._ask_confirmation(outcome.get(
                        "confirmation_message", "Another step needs confirmation."))
                else:
                    self._emit_workflow("finished")
                    self._emit_goal()
                    self._render_plan_summary(outcome)
            else:
                tool_manager.cancel_pending_confirmation()
                planning_engine.cancel_paused_plan()
                bus.emit("confirm_required", {"pending": False})
                self._clear_pending_origin()
                self._emit_workflow("cancelled")
                self._emit_goal()
                self._say("Cancelled — no changes were made.")
                self._decision("Policy", "User declined pending plan step; changes cancelled.")
            return

        # --- single destructive-tool confirmation -----------------------
        if tool_manager.has_pending_confirmation():
            self._agent("Constitution", "active", "approval decision")
            if is_confirm_answer(lowered):
                result = tool_manager.confirm_pending()
                bus.emit("confirm_required", {"pending": False})
                self._clear_pending_origin()
                msg = result.message or ("Done." if result.success else "That didn't work.")
                self._say(msg, kind="tool")
                self._state("success" if result.success else "error",
                            "" if result.success else (result.error or "tool failed"))
            else:
                tool_manager.cancel_pending_confirmation()
                bus.emit("confirm_required", {"pending": False})
                self._clear_pending_origin()
                self._say("Cancelled — no changes were made.")
                self._decision("Policy", "User declined destructive action; cancelled.")
            return

        # --- mid-clarification: this input answers the pending question -
        if session.get_current_question():
            param = session.get_current_question()
            session.update_parameters({param: text})
            session.clear_current_question()
            original_text = session.get_last_user_text()
            text = f"{original_text}\n{param}: {text}" if original_text else text
            user_text = text

        session.set_last_user_text(text)

        # --- context build: memory → knowledge → cognition → capability →
        #     reasoning → runtime intelligence (same order as main.py) ---
        t0 = time.monotonic()
        self._agent("Knowledge", "active", "retrieving context")
        self._state("searching", "retrieving memory and knowledge")
        long_term_memory = load_memory()
        memory_for_prompt = minimal_memory_for_prompt(long_term_memory)
        retrieved = self.knowledge.retrieve_context(text, limit=5)
        if retrieved:
            memory_for_prompt["retrieved_knowledge"] = retrieved
        cognitive_context = self.cognition.prepare(text)
        memory_for_prompt["reasoning_mode"] = cognitive_context.mode.name
        memory_for_prompt["reasoning_rules"] = "; ".join(cognitive_context.mode.rules)
        if cognitive_context.gap:
            memory_for_prompt["knowledge_gap"] = cognitive_context.gap.question
        capability_context = self.capabilities.prepare(text)
        reasoning_result = self.reasoning.reason(text, list(capability_context.records))
        memory_for_prompt["reasoning_strategy"] = reasoning_result.strategy
        memory_for_prompt["reasoning_confidence"] = f"{reasoning_result.confidence:.2f}"
        if reasoning_result.inferences:
            memory_for_prompt["revisable_hypotheses"] = "; ".join(
                item.statement for item in reasoning_result.inferences)
        memory_for_prompt["capability_strategy"] = capability_context.strategy
        if capability_context.gap:
            memory_for_prompt["capability_gap"] = capability_context.gap.missing
        elif capability_context.records:
            memory_for_prompt["capability_experience"] = "\n".join(
                r["content"] for r in capability_context.records[:3])
        self._agent("Runtime Intel", "active", "composition & simulation")
        runtime_context = self.runtime_intelligence.prepare(text, list(capability_context.records))
        memory_for_prompt["capability_composition"] = runtime_context["composition"]["strategy"]
        if runtime_context["prior_projects"]:
            memory_for_prompt["project_continuity"] = runtime_context["prior_projects"][0]["content"]
        self._stage("context", "done", {
            "reasoning_mode": cognitive_context.mode.name,
            "reasoning_strategy": reasoning_result.strategy,
            "reasoning_confidence": round(reasoning_result.confidence, 3),
            "retrieved": bool(retrieved),
        }, duration=time.monotonic() - t0)

        history_lines = session.get_history_for_prompt()
        recent_history = "\n".join(history_lines.split("\n")[-5:])
        if recent_history:
            memory_for_prompt["recent_conversation"] = recent_history

        if session.has_pending_intent():
            memory_for_prompt["_pending_intent"] = session.pending_intent
            memory_for_prompt["_collected_params"] = str(session.get_parameters())

        # --- Intent Engine: classify (+ Fast Planner), zero LLM cost ----
        self._agent("Intent Engine", "active")
        t0 = time.monotonic()
        classification, fast_result = classify_and_fast_handle(text, memory_for_prompt)
        try:
            cls = classification.to_dict()
        except Exception:
            cls = {"intent": str(classification.intent), "confidence": None}
        self._stage("intent", "done", cls, duration=time.monotonic() - t0)

        # Adaptive workspace follows the Core's own classification.
        workspace = _workspace_for(classification, text)
        if workspace in WORKSPACES:
            bus.emit("workspace", {"mode": workspace, "source": "classification",
                                   "confidence": cls.get("confidence")})

        # Focus mode: multi-step work collapses peripheral UI.
        if classification.intent == Intent.PLANNER or (cls.get("estimated_tool_count") or 0) >= 2:
            bus.emit("focus", {"active": True, "reason": "multi-step task"})

        if fast_result is not None:
            if fast_result.get("tool_used"):
                self._agent("Fast Planner", "active", f"tool: {fast_result['tool_used']}")
                bus.emit("tool", {"phase": "end", "tool": fast_result["tool_used"],
                                  "success": True, "via": "fast_planner"})
            else:
                self._agent("Fast Planner", "active", "answered locally, no LLM call")
            self._state("speaking")
            reply = fast_result.get("text", "")
            session.set_last_ai_response(reply)
            self._say(reply)
            self._decision("Intent Engine", "Fast Planner answered with zero LLM cost.")
            return

        # --- AI Planner (gated exactly like main.py) --------------------
        plan_outcome = None
        if config.PLANNER_ENABLED and classification.needs_planning:
            self._agent("AI Planner", "active", "decomposing goal")
            bus.emit("workspace", {"mode": "automation", "source": "planner"})
            t0 = time.monotonic()
            try:
                plan_outcome = planning_engine.handle_request(text, memory_for_prompt, recent_history)
            except Exception as e:
                bus.emit("log", {"level": "WARNING",
                                 "text": f"planner error, falling back to normal chat: {e}"})
                plan_outcome = None
            self._stage("planner", "done" if plan_outcome else "skipped",
                        {"outcome": bool(plan_outcome)}, duration=time.monotonic() - t0)

        if plan_outcome is not None:
            session.set_last_ai_response(plan_outcome.get("goal", ""))
            self._emit_goal()
            if plan_outcome.get("paused"):
                self._emit_workflow("paused")
                self._ask_confirmation(plan_outcome.get(
                    "confirmation_message", "This step needs confirmation."))
            else:
                self._emit_workflow("finished")
                self._state("success")
                self._render_plan_summary(plan_outcome)
            return

        # --- LLM (main.py's ui.start_speaking → core_state: thinking) ---
        self._state("thinking", "contacting the model")
        t0 = time.monotonic()
        started_at = t0
        try:
            llm_output = get_llm_output(user_text=text, memory_block=memory_for_prompt)
        except Exception as e:
            self._stage("llm", "error", {"error": str(e)})
            self._state("error", "model unreachable")
            self._say(f"AI ERROR: {e}", kind="error")
            return
        self._stage("llm", "done", {"intent": llm_output.get("intent", "chat")},
                    duration=time.monotonic() - t0)

        intent = llm_output.get("intent", "chat")
        parameters = llm_output.get("parameters", {}) or {}
        response = llm_output.get("text")
        memory_update = llm_output.get("memory_update")

        # --- Self-Critic (optional, same gate as main.py) ---------------
        if config.ENABLE_SELF_CRITIC and intent == "chat" and response:
            self._agent("Self-Critic", "active", "reviewing draft")
            t0 = time.monotonic()
            try:
                critique = self_critic.review(text, response, reasoning_result.confidence)
                if critique.should_improve:
                    self._decision("Self-Critic",
                                   "Revising response: " + "; ".join(critique.reasons))
                    response = self_critic.improve(text, response, critique)
                else:
                    self._decision("Self-Critic", "Draft accepted without changes.")
                self._stage("self_critic", "done", {
                    "revised": bool(critique.should_improve),
                    "reasons": list(getattr(critique, "reasons", []) or []),
                }, duration=time.monotonic() - t0)
            except Exception as critic_error:
                bus.emit("log", {"level": "WARNING",
                                 "text": f"self-critic deferred: {critic_error}"})

        # --- memory + learning (mirrors main.py) -------------------------
        if memory_update and isinstance(memory_update, dict):
            self._state("updating", "writing long-term memory")
            update_memory(memory_update)
            bus.emit("memory_update", {"keys": list(memory_update.keys())})

        try:
            self._agent("Learning", "active", "recording experience")
            self._state("learning", "consolidating experience")
            self.learning.learn_task(text, response or "", elapsed=time.monotonic() - started_at)
            self.capabilities.learn(text, "normal LLM response", bool(response),
                                    .65 if response else .3)
            self.runtime_intelligence.complete(text, response or "",
                                               time.monotonic() - started_at,
                                               list(capability_context.records))
        except Exception as learning_error:
            bus.emit("log", {"level": "WARNING", "text": f"learning deferred: {learning_error}"})

        session.set_last_ai_response(response)

        if intent and intent != "chat":
            self._handle_intent(intent, parameters, response)
        else:
            if response:
                self._state("speaking")
                self._say(response)
                self._state("success")
        self._emit_goal()

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
            self._agent("Tool Manager", "active", intent)
            bus.emit("tool", {"phase": "start", "tool": intent, "parameters": parameters})
            self._state("coding" if intent in ("run_python", "run_shell") else "thinking",
                        f"running {intent}")
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
