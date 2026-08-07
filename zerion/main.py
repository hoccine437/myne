# main.py
"""
Mark-X Lite — terminal-first AI assistant.

Same conversation loop, memory handling, and intent contract as the
original Mark-X, minus the GUI and desktop-automation layers that don't
belong on Termux / low-resource Linux.
"""

import config
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
from terminal import TerminalUI
from speech import speak, speech_status
from tools.manager import tool_manager
from planner import planner as planning_engine
from intent import commands as command_palette
from intent.engine import process as classify_and_fast_handle
from intent.models import Intent

from memory.memory_manager import load_memory, update_memory

INTERRUPT_COMMANDS = {"quit", "exit", "stop"}


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


def _render_plan_summary(summary: dict, ui: TerminalUI):
    """Turn a planner execution summary into a short spoken/printed
    report — which steps ran, which failed, overall outcome."""
    tasks = summary.get("tasks", [])
    done = [t for t in tasks if t["state"] == "completed"]
    failed = [t for t in tasks if t["state"] == "failed"]

    if summary.get("all_succeeded"):
        msg = f"Done — completed all {len(done)} step(s) for: {summary.get('goal', '')}"
    elif summary.get("aborted"):
        msg = (f"Stopped partway through '{summary.get('goal', '')}' — "
               f"{len(done)} step(s) succeeded, {len(failed)} failed.")
    else:
        msg = (f"Finished '{summary.get('goal', '')}' with some issues — "
               f"{len(done)} step(s) succeeded, {len(failed)} failed or skipped.")

    ui.write_log(f"AI: {msg}")
    speak(msg)


def handle_intent(intent: str, parameters: dict, response: str, ui: TerminalUI, session: SessionMemory):
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


def run_loop(ui: TerminalUI):
    session = SessionMemory()
    # Phase 4 is additive: legacy memory and all existing engines remain intact.
    knowledge = KnowledgeManager()
    learning = LearningEngine()
    capabilities = CapabilityEvolution()
    background = BackgroundLearning()
    cognition = CognitiveEngine()
    reasoning = CognitiveReasoningEngine()
    runtime_intelligence = RuntimeIntelligence()
    phone = PhoneIntelligence()
    pending_phone = None
    pending_phone_missing = None

    print("Mark-X Lite — type 'exit' to quit.")
    print(speech_status())

    while True:
        user_text = ui.get_input()

        if not user_text or not user_text.strip():
            # Idle work is bounded and automatically load-aware. Memory
            # consolidation runs via BackgroundLearning (existing); weak
            # capability reporting reuses the CapabilityQuality tracker
            # RuntimeIntelligence already maintains every turn, so this
            # doesn't duplicate BackgroundMaintenance's own consolidate()
            # call -- it only adds the one thing that tracker doesn't
            # already do: reporting the result somewhere visible.
            maintenance_result = background.run_once()
            if maintenance_result:
                log.debug(f"idle maintenance: {maintenance_result}")
            weak = runtime_intelligence.quality.weak()
            if weak:
                log.debug(f"idle maintenance: weak capabilities: {', '.join(weak)}")
            continue

        if user_text.strip().lower() in INTERRUPT_COMMANDS:
            print("Goodbye.")
            break

        if user_text.strip().lower() == "mute":
            session.reset()
            continue

        if pending_phone is not None:
            if user_text.strip().lower() in ("confirm", "yes", "y"):
                goal, intent = pending_phone
                result = phone.dispatcher.dispatch(goal, intent, approved=True)
                ui.write_log(f"AI: {result.message}")
                speak(result.message)
            else:
                ui.write_log("AI: Cancelled — no phone action was performed.")
            pending_phone = None
            continue

        if pending_phone_missing is not None:
            # Previous turn was a phone intent missing required info (e.g.
            # "call father" had no number). Treat this message as supplying
            # it, rather than routing it to the LLM as ordinary chat --
            # otherwise "confirm"/etc. here would fall through every pending
            # state check below and hit the network unnecessarily.
            goal_text, extracted_phone = pending_phone_missing
            retry_text = f"{goal_text} {user_text}".strip()
            extracted_phone = phone.extractor.extract(retry_text) or extracted_phone
            if extracted_phone.missing:
                ui.write_log(
                    "AI: Still missing: " + ", ".join(extracted_phone.missing)
                    + ". Reply with that, or say 'cancel'."
                )
                if user_text.strip().lower() == "cancel":
                    pending_phone_missing = None
                    ui.write_log("AI: Cancelled.")
                else:
                    pending_phone_missing = (goal_text, extracted_phone)
                continue
            pending_phone_missing = None
            result = phone.dispatcher.dispatch(retry_text, extracted_phone, approved=False)
            if "Approval required" in result.message:
                pending_phone = (retry_text, extracted_phone)
                ui.write_log(f"AI: {result.message} Reply 'confirm' to proceed.")
            else:
                ui.write_log(f"AI: {result.message}")
            continue

        extracted_phone = phone.extractor.extract(user_text)
        if extracted_phone is not None:
            if extracted_phone.missing:
                pending_phone_missing = (user_text, extracted_phone)
                ui.write_log("AI: Missing required information: " + ", ".join(extracted_phone.missing) + ".")
                continue
            result = phone.dispatcher.dispatch(user_text, extracted_phone, approved=False)
            if "Approval required" in result.message:
                pending_phone = (user_text, extracted_phone)
                ui.write_log(f"AI: {result.message} Reply 'confirm' to proceed.")
            else:
                ui.write_log(f"AI: {result.message}")
            continue

        # Command palette: handled entirely locally, before anything else,
        # so these always work even mid-confirmation or with no API key.
        if command_palette.is_command(user_text):
            memory_snapshot = minimal_memory_for_prompt(load_memory())
            output = command_palette.handle(user_text, session, memory_snapshot)
            ui.write_log(f"AI: {output}")
            continue

        # A multi-step plan is paused waiting on a destructive-tool
        # confirmation partway through. Checked before the single-tool
        # confirmation below, since a plan's confirmation takes priority
        # over any stray pending single-tool call.
        if planning_engine.has_paused_plan():
            if user_text.strip().lower() in ("confirm", "yes", "y"):
                pending_tool_result = None
                if tool_manager.has_pending_confirmation():
                    pending_tool_result = tool_manager.confirm_pending()
                if pending_tool_result is None:
                    ui.write_log("AI: Nothing to confirm right now.")
                    continue
                outcome = planning_engine.resume_paused_plan(pending_tool_result)
                if outcome.get("paused"):
                    ui.write_log(f"AI: {outcome.get('confirmation_message', 'Another step needs confirmation.')}")
                    speak(outcome.get("confirmation_message", ""))
                else:
                    _render_plan_summary(outcome, ui)
            else:
                tool_manager.cancel_pending_confirmation()
                planning_engine.cancel_paused_plan()
                ui.write_log("AI: Cancelled — no changes were made.")
                speak("Cancelled. No changes were made.")
            continue

        # A destructive tool (delete/move/run shell, etc.) is waiting on a
        # yes/no before it will actually execute.
        if tool_manager.has_pending_confirmation():
            if user_text.strip().lower() in ("confirm", "yes", "y"):
                result = tool_manager.confirm_pending()
                msg = result.message or ("Done." if result.success else "That didn't work.")
                ui.write_log(f"AI: {msg}")
                speak(msg)
            else:
                tool_manager.cancel_pending_confirmation()
                ui.write_log("AI: Cancelled — no changes were made.")
                speak("Cancelled. No changes were made.")
            continue

        # If we're mid multi-step intent, treat this input as the answer
        # to the last clarification question. The just-given answer is
        # appended to the original request so both are visible to the LLM
        # this turn (previously this discarded the user's new reply and
        # resent only the original message).
        if session.get_current_question():
            param = session.get_current_question()
            session.update_parameters({param: user_text})
            session.clear_current_question()
            original_text = session.get_last_user_text()
            user_text = f"{original_text}\n{param}: {user_text}" if original_text else user_text

        session.set_last_user_text(user_text)

        long_term_memory = load_memory()
        memory_for_prompt = minimal_memory_for_prompt(long_term_memory)
        # Retrieval happens before planning/LLM. It is local SQLite + token
        # semantic-overlap ranking, so it is safe on Termux without models.
        retrieved = knowledge.retrieve_context(user_text, limit=5)
        if retrieved:
            memory_for_prompt["retrieved_knowledge"] = retrieved
        # Goal-first cognition creates an ephemeral mode for this request.
        # Legacy skills stay available as compatibility metadata, not control flow.
        cognitive_context = cognition.prepare(user_text)
        memory_for_prompt["reasoning_mode"] = cognitive_context.mode.name
        memory_for_prompt["reasoning_rules"] = "; ".join(cognitive_context.mode.rules)
        if cognitive_context.gap:
            memory_for_prompt["knowledge_gap"] = cognitive_context.gap.question
        capability_context = capabilities.prepare(user_text)
        reasoning_result = reasoning.reason(user_text, list(capability_context.records))
        memory_for_prompt["reasoning_strategy"] = reasoning_result.strategy
        memory_for_prompt["reasoning_confidence"] = f"{reasoning_result.confidence:.2f}"
        if reasoning_result.inferences:
            memory_for_prompt["revisable_hypotheses"] = "; ".join(item.statement for item in reasoning_result.inferences)
        memory_for_prompt["capability_strategy"] = capability_context.strategy
        if capability_context.gap:
            memory_for_prompt["capability_gap"] = capability_context.gap.missing
        elif capability_context.records:
            memory_for_prompt["capability_experience"] = "\n".join(r['content'] for r in capability_context.records[:3])
        runtime_context = runtime_intelligence.prepare(user_text, list(capability_context.records))
        memory_for_prompt["capability_composition"] = runtime_context["composition"]["strategy"]
        if runtime_context["prior_projects"]:
            memory_for_prompt["project_continuity"] = runtime_context["prior_projects"][0]["content"]

        history_lines = session.get_history_for_prompt()
        recent_history = "\n".join(history_lines.split("\n")[-5:])
        if recent_history:
            memory_for_prompt["recent_conversation"] = recent_history

        if session.has_pending_intent():
            memory_for_prompt["_pending_intent"] = session.pending_intent
            memory_for_prompt["_collected_params"] = str(session.get_parameters())

        # Intent Engine: classify (zero LLM cost) and try the Fast Planner
        # (zero LLM cost for memory lookups and safe zero-parameter tool
        # calls). If this fully answers the request, we're done for this
        # turn with no LLM call at all.
        classification, fast_result = classify_and_fast_handle(user_text, memory_for_prompt)

        if fast_result is not None:
            text = fast_result.get("text", "")
            session.set_last_ai_response(text)
            ui.write_log(f"AI: {text}")
            speak(text)
            continue

        # Try the AI Planner only when the Intent Engine's classification
        # actually signals a multi-step request -- replaces the previous
        # word-count heuristic with real classification signal. Still
        # gated by PLANNER_ENABLED since it costs one extra LLM call.
        plan_outcome = None
        if config.PLANNER_ENABLED and classification.needs_planning:
            try:
                plan_outcome = planning_engine.handle_request(user_text, memory_for_prompt, recent_history)
            except Exception as e:
                print(f"(planner error, falling back to normal chat: {e})")
                plan_outcome = None

        if plan_outcome is not None:
            session.set_last_ai_response(plan_outcome.get("goal", ""))
            if plan_outcome.get("paused"):
                ui.write_log(f"AI: {plan_outcome.get('confirmation_message', 'This step needs confirmation.')}")
                speak(plan_outcome.get("confirmation_message", ""))
            else:
                _render_plan_summary(plan_outcome, ui)
            continue

        ui.start_speaking()
        started_at = time.monotonic()
        try:
            llm_output = get_llm_output(user_text=user_text, memory_block=memory_for_prompt)
        except Exception as e:
            ui.stop_speaking()
            ui.write_log(f"AI ERROR: {e}")
            continue
        ui.stop_speaking()

        intent = llm_output.get("intent", "chat")
        parameters = llm_output.get("parameters", {}) or {}
        response = llm_output.get("text")
        memory_update = llm_output.get("memory_update")

        # Self-Critic: review the draft against this turn's reasoning
        # confidence (already computed above) plus cheap structural
        # checks, before anything is stored or sent. Only chat-intent
        # replies are reviewed -- a tool/intent result isn't free text
        # the critic can usefully rewrite. Fully optional: when
        # config.ENABLE_SELF_CRITIC is False, this block is skipped
        # entirely and the pipeline behaves exactly as it did before the
        # critic existed. Non-fatal: any critic failure falls back to the
        # original draft untouched. At most one review() and one
        # improve() call per turn -- see intelligence/critic.py's module
        # docstring for why this can never become a feedback loop.
        if config.ENABLE_SELF_CRITIC and intent == "chat" and response:
            try:
                critique = self_critic.review(user_text, response, reasoning_result.confidence)
                if critique.should_improve:
                    log.info(f"self-critic: revising response ({'; '.join(critique.reasons)})")
                    response = self_critic.improve(user_text, response, critique)
            except Exception as critic_error:
                print(f"(self-critic deferred: {critic_error})")

        if memory_update and isinstance(memory_update, dict):
            update_memory(memory_update)

        # Store an experience and reflection after material completions.
        # Failures are captured by exceptions; this path remains non-fatal.
        try:
            learning.learn_task(user_text, response or "", elapsed=time.monotonic() - started_at)
            capabilities.learn(user_text, "normal LLM response", bool(response), .65 if response else .3)
            runtime_intelligence.complete(user_text, response or "", time.monotonic() - started_at, list(capability_context.records))
        except Exception as learning_error:
            print(f"(learning deferred: {learning_error})")

        session.set_last_ai_response(response)

        if intent and intent != "chat":
            handle_intent(intent, parameters, response, ui, session)
        else:
            if response:
                ui.write_log(f"AI: {response}")
                speak(response)


def main():
    # Load and integrity-check once at startup; all normal requests reuse cache.
    ConstitutionEngine.load()
    for warning in config.validate():
        print(f"[configuration] {warning}")
    ui = TerminalUI()
    try:
        run_loop(ui)
    except KeyboardInterrupt:
        print("\nGoodbye.")


if __name__ == "__main__":
    main()
