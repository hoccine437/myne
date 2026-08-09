# core/turn_runner.py
"""The canonical turn lifecycle — ONE implementation for both front ends.

History (brief, and over now): main.py:run_loop and ui/session._run_turn
were kept line-mirrored, each owning a copy of the branch chain
(interrupt → mute → phone → palette → planner-pause → tool-confirm →
clarification → context → intent → planner? → llm → critic → memory →
learning → dispatch). The mirror was a contract test, not a real seam.

This module now owns that sequence. Front ends supply ONLY a surface:

    TurnSink methods (all optional, all no-op safe):
      say(text, kind="")        — assistant-visible message
      write(text) / speak(text) — terminal or voice
      state(state, detail="")   core_state (thinking/analyzing/learning…)
      stage(name,status,detail,duration)  pipeline stage telemetry
      decision(source, text)    notable Core decision
      notify(text, level)       toast/print-level note
      confirm_required(payload) ask the user to approve
      phone_state(snap)         device body snapshot event
      workspace(mode, source, confidence)
      focus(payload)            focus mode notification
      workflow(reason)          planner snapshot emission
      goal()                    goal state emission
      no_desktop_actions()        legacy desktop-action refusal line (front-end flavored)
      on_interrupt_reason()       farewell line if any ('' → caller prints its own)
      agent_row(name,state,detail)        System-panel activity row

Terminal (main.py) implements write/speak by print() + speech.speak();
the UI session maps each sink call to its existing event shapes.

Nothing here is new logic: bodies decanted from the duplicated loops —
identical tests pass because identical behavior ships.
"""

from __future__ import annotations

import threading
import time

import config
from core import logging as log
from core.turn_pipeline import (INTERRUPT_COMMANDS, is_confirm_answer,
                                plan_summary_text)


class TurnRunner:
    """One turn of ONE front end. Composable: the caller passes its own
    session state (SessionMemory) and engine set; TurnRunner never creates
    new engines — it only orchestrates the caller's objects."""

    def __init__(self, state, engines: dict, sink, pending: dict | None = None):
        self.state = state
        self._engines = engines
        self.sink = sink
        self.pending = pending if pending is not None else {
            "phone": None, "phone_missing": None}

    # ------------------------------------------------------------------
    # the public turn
    # ------------------------------------------------------------------

    def run(self, user_text: str) -> str:
        """Process one message. Returns 'continue' (loop keeps going) or
        'exit' (interrupt words — caller decides how to end; e.g. print
        goodbye or mark session ended)."""
        text = (user_text or "").strip()
        if not text:
            return "continue"

        session = self.state

        # interrupt words — the farewell line is a front-end concern
        if text.lower() in INTERRUPT_COMMANDS:
            reason = self.sink.on_interrupt_reason()
            if reason:
                self.sink.say(reason)
            return "exit"

        # mute → reset session
        if text.lower() == "mute":
            session.reset()
            self.sink.decision("Session", "Session context cleared (mute).")
            self.sink.say("Context cleared. Fresh session.")
            return "continue"

        # pending phone approval
        if self.pending["phone"] is not None:
            if is_confirm_answer(text):
                goal, intent = self.pending["phone"]
                self.sink.agent_row("Tool Manager", "active", "phone dispatch (approved)")
                result = self.phone.dispatcher.dispatch(goal, intent, approved=True)
                self.sink.say(result.message)
                self._phone_state()
            else:
                self.sink.say("Cancelled — no phone action was performed.")
            self.pending["phone"] = None
            return "continue"

        # pending phone-missing-info
        if self.pending["phone_missing"] is not None:
            goal_text, extracted = self.pending["phone_missing"]
            retry_text = f"{goal_text} {text}".strip()
            extracted = self.phone.extractor.extract(retry_text) or extracted
            if extracted.missing:
                self.sink.say("Still missing: " + ", ".join(extracted.missing)
                              + ". Reply with that, or say 'cancel'.")
                if text.lower() == "cancel":
                    self.pending["phone_missing"] = None
                    self.sink.say("Cancelled.")
                else:
                    self.pending["phone_missing"] = (goal_text, extracted)
                return "continue"
            self.pending["phone_missing"] = None
            result = self.phone.dispatcher.dispatch(retry_text, extracted,
                                                    approved=False)
            if "Approval required" in result.message:
                self.pending["phone"] = (retry_text, extracted)
                self.sink.confirm_required({"pending": True, "tool": "phone",
                                            "message": result.message})
                self.sink.say(result.message + " Reply 'confirm' to proceed.",
                              kind="confirm")
            else:
                self.sink.say(result.message)
            self._phone_state()
            return "continue"

        # fresh phone intent
        extracted = self.phone.extractor.extract(text)
        if extracted is not None:
            self.sink.agent_row("Tool Manager", "active", "phone intent")
            if extracted.missing:
                self.pending["phone_missing"] = (text, extracted)
                self.sink.say("Missing required information: "
                              + ", ".join(extracted.missing) + ".")
                return "continue"
            result = self.phone.dispatcher.dispatch(text, extracted,
                                                    approved=False)
            if "Approval required" in result.message:
                self.pending["phone"] = (text, extracted)
                self.sink.confirm_required({"pending": True, "tool": "phone",
                                            "message": result.message})
                self.sink.say(result.message + " Reply 'confirm' to proceed.",
                              kind="confirm")
            else:
                self.sink.say(result.message)
            self._phone_state()
            return "continue"

        # command palette (all local)
        if self.tool_command_palette.is_command(text):
            self.sink.agent_row("Intent Engine", "active", "command palette")
            memory_snapshot = self.minimal_reducer(self.load_memory())
            output = self.tool_command_palette.handle(
                text, session, memory_snapshot)
            self.sink.say(output, kind="command")
            self.sink.goal()
            return "continue"

        # paused-plan confirmation (highest-priority pending)
        if self.planner.has_paused_plan():
            self.sink.agent_row("AI Planner", "active", "paused plan decision")
            if is_confirm_answer(text):
                pending_tool_result = None
                if self.tool_manager.has_pending_confirmation():
                    pending_tool_result = self.tool_manager.confirm_pending()
                if pending_tool_result is None:
                    self.sink.say("Nothing to confirm right now.")
                    self.sink.confirm_required({"pending": False})
                    return "continue"
                self.sink.confirm_required({"pending": False})
                self.sink.workflow("resumed")
                outcome = self.planner.resume_paused_plan(pending_tool_result)
                if outcome.get("paused"):
                    self.sink.workflow("paused")
                    self.sink.confirm_required(
                        {"pending": True,
                         "message": outcome.get("confirmation_message",
                                                "Another step needs confirmation."),
                         "tool": outcome.get("tool", "")})
                    self.sink.say(outcome.get("confirmation_message",
                                              "Another step needs confirmation."),
                                  kind="confirm")
                else:
                    self.sink.workflow("finished")
                    self.sink.goal()
                    msg = plan_summary_text(outcome)
                    self.sink.state("success" if outcome.get("all_succeeded")
                                    else "warning")
                    self.sink.say(msg, kind="plan")
            else:
                self.tool_manager.cancel_pending_confirmation()
                self.planner.cancel_paused_plan()
                self.sink.confirm_required({"pending": False})
                self.sink.workflow("cancelled")
                self.sink.goal()
                self.sink.say("Cancelled — no changes were made.")
                self.sink.decision("Policy",
                                   "User declined pending plan step; changes cancelled.")
            return "continue"

        # single destructive-tool confirmation
        if self.tool_manager.has_pending_confirmation():
            self.sink.agent_row("Constitution", "active", "approval decision")
            if is_confirm_answer(text):
                result = self.tool_manager.confirm_pending()
                self.sink.confirm_required({"pending": False})
                self.sink.tool_event("end", self._pending_tool_name(), result)
                msg = result.message or ("Done." if result.success
                                         else "That didn't work.")
                self.sink.say(msg, kind="tool")
                self.sink.state("success" if result.success else "error",
                                "" if result.success else (result.error or "tool failed"))
            else:
                self.tool_manager.cancel_pending_confirmation()
                self.sink.confirm_required({"pending": False})
                self.sink.say("Cancelled — no changes were made.")
                self.sink.decision("Policy",
                                   "User declined destructive action; cancelled.")
            return "continue"

        # clarification mid-question
        if session.get_current_question():
            param = session.get_current_question()
            session.update_parameters({param: text})
            session.clear_current_question()
            original_text = session.get_last_user_text()
            text = (f"{original_text}\n{param}: {text}"
                    if original_text else text)
            user_text = text

        session.set_last_user_text(text)

        # ---------------- context build (identical chain) ----------------
        t0 = time.monotonic()
        self.sink.agent_row("Knowledge", "active", "retrieving context")
        self.sink.state("analyzing", "assembling reasoning context")
        long_term_memory = self.load_memory()
        memory_for_prompt = self.minimal_reducer(long_term_memory)
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
        self.sink.agent_row("Runtime Intel", "active", "composition & simulation")
        runtime_context = self.runtime_intelligence.prepare(
            text, list(capability_context.records))
        memory_for_prompt["capability_composition"] = runtime_context["composition"]["strategy"]
        if runtime_context["prior_projects"]:
            memory_for_prompt["project_continuity"] = \
                runtime_context["prior_projects"][0]["content"]
        self.sink.stage("context", "done", {
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

        # ---------------- intent engine (+fast/consult lanes) -------------
        self.sink.agent_row("Intent Engine", "active")
        t0 = time.monotonic()
        classification, fast_result = self.intent_process(text, memory_for_prompt)
        try:
            cls = classification.to_dict()
        except Exception:
            cls = {"intent": str(classification.intent), "confidence": None}
        self.sink.stage("intent", "done", cls, duration=time.monotonic() - t0)
        self.sink.post_classification(classification, text, cls)

        if fast_result is not None:
            if fast_result.get("tool_used"):
                self.sink.agent_row("Fast Planner", "active",
                                    f"tool: {fast_result['tool_used']}")
                self.sink.state("executing",
                                f"fast tool {fast_result['tool_used']}")
                self.sink.tool_event("end", fast_result["tool_used"],
                                     None, via="fast_planner")
            else:
                self.sink.agent_row("Fast Planner", "active",
                                    "answered locally, no LLM call")
            self.sink.state("speaking")
            reply = fast_result.get("text", "")
            session.set_last_ai_response(reply)
            self.sink.say(reply)
            self.sink.decision("Intent Engine",
                               "Fast Planner answered with zero LLM cost.")
            return "continue"

        # ---------------- planner (new canonical gating) ------------------
        plan_outcome = None
        if config.planner_active(classification.needs_planning):
            self.sink.agent_row("AI Planner", "active", "decomposing goal")
            self.sink.workspace("automation", "planner", None)
            t0 = time.monotonic()
            try:
                plan_outcome = self.planner.handle_request(
                    text, memory_for_prompt, recent_history)
            except Exception as e:
                self.sink.log("WARNING",
                              f"planner error, falling back to normal chat: {e}")
                plan_outcome = None
            self.sink.stage("planner", "done" if plan_outcome else "skipped",
                            {"outcome": bool(plan_outcome)},
                            duration=time.monotonic() - t0)

        if plan_outcome is not None:
            session.set_last_ai_response(plan_outcome.get("goal", ""))
            self.sink.goal()
            if plan_outcome.get("paused"):
                self.sink.workflow("paused")
                self.sink.confirm_required(
                    {"pending": True,
                     "message": plan_outcome.get("confirmation_message",
                                                 "This step needs confirmation.")})
                self.sink.say(plan_outcome.get("confirmation_message",
                                               "This step needs confirmation."),
                              kind="confirm")
            else:
                self.sink.workflow("finished")
                self.sink.state("success")
                self.sink.state("warning" if not plan_outcome.get("all_succeeded")
                                else "success")
                self.sink.say(plan_summary_text(plan_outcome), kind="plan")
            return "continue"

        # ---------------- LLM (the only provider call) --------------------
        self.sink.state("thinking", "contacting the model")
        t0 = time.monotonic()
        started_at = t0
        try:
            llm_output = self.llm_call(text, memory_for_prompt)
        except Exception as e:
            self.sink.stage("llm", "error", {"error": str(e)},
                            duration=time.monotonic() - t0)
            self.sink.state("error", "model unreachable")
            self.sink.say(f"AI ERROR: {e}", kind="error")
            return "continue"
        self.sink.stage("llm", "done", {"intent": llm_output.get("intent", "chat")},
                        duration=time.monotonic() - t0)

        intent = llm_output.get("intent", "chat")
        parameters = llm_output.get("parameters", {}) or {}
        response = llm_output.get("text")
        memory_update = llm_output.get("memory_update")

        # ---------------- self-critic (optional) --------------------------
        if config.ENABLE_SELF_CRITIC and intent == "chat" and response:
            self.sink.agent_row("Self-Critic", "active", "reviewing draft")
            t0 = time.monotonic()
            try:
                from intelligence.critic import self_critic
                critique = self_critic.review(text, response,
                                              reasoning_result.confidence)
                if critique.should_improve:
                    self.sink.decision("Self-Critic",
                                       "Revising response: " + "; ".join(critique.reasons))
                    response = self_critic.improve(text, response, critique)
                else:
                    self.sink.decision("Self-Critic", "Draft accepted without changes.")
                self.sink.stage("self_critic", "done", {
                    "revised": bool(critique.should_improve),
                    "reasons": list(getattr(critique, "reasons", []) or []),
                }, duration=time.monotonic() - t0)
            except Exception as critic_error:
                self.sink.log("WARNING", f"self-critic deferred: {critic_error}")

        # ---------------- memory update + learning -------------------------
        if memory_update and isinstance(memory_update, dict):
            self.sink.state("updating", "writing long-term memory")
            self.update_memory(memory_update)
            self.sink.notify("memory updated: " + ", ".join(memory_update.keys()),
                             level="info")
            self.sink.memory_update(memory_update)

        try:
            self.sink.agent_row("Learning", "active", "recording experience")
            self.sink.state("learning", "consolidating experience")
            self.learning.learn_task(text, response or "",
                                     elapsed=time.monotonic() - started_at)
            self.capabilities.learn(text, "normal LLM response",
                                    bool(response), .65 if response else .3)
            self.runtime_intelligence.complete(
                text, response or "", time.monotonic() - started_at,
                list(capability_context.records))
        except Exception as learning_error:
            self.sink.log("WARNING", f"learning deferred: {learning_error}")

        session.set_last_ai_response(response)

        if intent and intent != "chat":
            self._dispatch_intent(intent, parameters, response)
        else:
            if response:
                self.sink.state("speaking")
                self.sink.say(response)
                self.sink.state("success")
        self.sink.goal()
        return "continue"

    # ------------------------------------------------------------------
    # intent dispatch — full branch (identical semantics both front ends)
    # ------------------------------------------------------------------

    def _dispatch_intent(self, intent: str, parameters: dict, response: str) -> None:
        if intent in ("open_app", "send_message"):
            msg = (response or self.sink.no_desktop_actions())
            self.sink.say(msg)
            self.state.clear_pending_intent()
            return

        tool = self.tool_manager.get_tool(intent)
        if tool is not None:
            if intent in ("agent_delegate", "agent_orchestrate", "agent_performance",
                          "agent_status"):
                self.sink.agent_row("Agent Orchestrator", "active", intent)
            self.sink.agent_row("Tool Manager", "active", intent)
            self.sink.tool_event("start", intent, None, destructive=tool.destructive,
                                 parameters=parameters)
            self.sink.state("executing", f"executing {intent}")
            result = self.tool_manager.execute(intent, parameters)
            if result.error == "confirmation_required":
                self.sink.tool_event("confirm", intent, None,
                                     parameters=parameters, message=result.message)
                self.sink.confirm_required({"pending": True, "tool": intent,
                                            "parameters": parameters,
                                            "message": result.message})
                self.sink.say(result.message, kind="confirm")
                return
            self.sink.tool_event("end", intent, result)
            msg = result.message or (response or "")
            self.sink.say(msg, kind="tool")
            self.sink.state("success" if result.success else "error",
                            "" if result.success else (result.error or "tool failed"))
            return

        # known words with no matching tool (weather_report, search, etc.):
        # the model's own response is the answer, same as always
        if response:
            self.sink.say(response)

    # ------------------------------------------------------------------
    # internals shared by all branches
    # ------------------------------------------------------------------

    def _phone_state(self) -> None:
        try:
            snap = self.phone.body.snapshot()
        except Exception:
            snap = None
        if snap is not None:
            self.sink.phone_state(snap)

    def _pending_tool_name(self) -> str:
        # one pending slot, enqueued last; read-only naming for telemetry
        try:
            if self.tool_manager._pending_confirmation:
                return self.tool_manager._pending_confirmation[0]
        except Exception:
            pass
        return ""

    # -- engine accessors (constructed once at the caller's side) ---------

    @property
    def knowledge(self): return self._engines["knowledge"]
    @property
    def learning(self): return self._engines["learning"]
    @property
    def capabilities(self): return self._engines["capabilities"]
    @property
    def cognition(self): return self._engines["cognition"]
    @property
    def reasoning(self): return self._engines["reasoning"]
    @property
    def runtime_intelligence(self): return self._engines["runtime_intelligence"]
    @property
    def phone(self): return self._engines["phone"]
    @property
    def tool_manager(self): return self._engines["tool_manager"]
    @property
    def planner(self): return self._engines["planner"]
    @property
    def tool_command_palette(self): return self._engines["command_palette"]
    @property
    def intent_process(self): return self._engines["intent_process"]
    @property
    def load_memory(self): return self._engines["load_memory"]
    @property
    def update_memory(self): return self._engines["update_memory"]
    @property
    def minimal_reducer(self): return self._engines["minimal_memory_for_prompt"]
    @property
    def llm_call(self):
        return self._engines["llm_call"]
