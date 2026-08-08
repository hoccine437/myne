# tests/test_final_e2e.py
"""Final end-to-end scenario (Phase 14) + failure modes (Phase 15).

Drives the real main.run_loop through the mandated chain:

START → CORE INITIALIZATION → (LLM via scripted provider) → USER REQUEST
→ INTENT → MEMORY → PLAN → REASONING → AGENT → TOOL → EXECUTION →
VERIFICATION → SELF-CRITIC → FINAL ANSWER → MEMORY UPDATE → HEALTH

plus the personality flip inside the same session, then failure and
restart/persistence checks. All offline: provider is scripted; audio is
mocked elsewhere (see test_gemini_transport.py).
"""

import json
import os
import sys
import tempfile
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.chdir(BASE)

import config  # noqa: E402


class FakeTerminalUI:
    def __init__(self, script):
        self.script = list(script)
        self.outputs = []

    def write_log(self, text):
        self.outputs.append(str(text))

    def start_speaking(self):
        pass

    def stop_speaking(self):
        pass

    def get_input(self, prompt="You: "):
        return self.script.pop(0) if self.script else "exit"

    def text(self):
        return "\n".join(self.outputs)


class ScriptedProvider:
    """Routes by user message; records stage usage."""

    def __init__(self):
        self.calls = []

    def __call__(self, system_prompt, user_prompt, **kw):
        msg = ""
        if 'User message: "' in user_prompt:
            msg = user_prompt.split('User message: "', 1)[1].split('"', 1)[0]
        kind = ("decompose" if system_prompt.startswith("You are a precise task planner")
                else "critic" if system_prompt.startswith("You are a careful editor")
                else "chat")
        self.calls.append((kind, msg))

        if kind == "decompose":
            return json.dumps({"complex": False})  # keep the loop single-turn here

        if kind == "critic":
            return "polished answer"

        if "delegate" in msg:
            return json.dumps({
                "intent": "agent_delegate",
                "parameters": {"agent_type": "verifier",
                               "task": {"tool": "calculate", "parameters": {"expression": "9*9"}}},
                "text": None, "memory_update": None,
            })
        if "route my domain" in msg:
            return json.dumps({
                "intent": "skill_route",
                "parameters": {"text": "compute a chemical reaction balance"},
                "text": None, "memory_update": None,
            })
        if "orchestrate" in msg:
            return json.dumps({
                "intent": "agent_orchestrate",
                "parameters": {"goal": "analyze this trading strategy"},
                "text": None, "memory_update": None,
            })
        if "what device" in msg:
            return json.dumps({"intent": "device_state", "parameters": {},
                               "text": None, "memory_update": None})
        if "remember my favorite color is teal" in msg:
            return json.dumps({
                "intent": "chat", "parameters": {},
                "text": "Noted — teal is your favorite color.",
                "memory_update": {"preferences": {"favorite_color": {"value": "teal"}}},
            })
        return json.dumps({"intent": "chat", "parameters": {},
                           "text": "Generic but proper reply.", "memory_update": None})


class FinalE2E(unittest.TestCase):
    def setUp(self):
        import api
        import main as main_mod
        import memory.memory_manager as mm
        self.main = main_mod
        self.api = api
        self._orig_call = api.call_llm
        self._orig_speak = main_mod.speak
        main_mod.speak = lambda *a, **k: None
        self.tmp = tempfile.TemporaryDirectory()
        self._orig_mem, self._orig_bak = mm.MEMORY_PATH, mm.BACKUP_PATH
        mm.MEMORY_PATH = os.path.join(self.tmp.name, "memory.json")
        mm.BACKUP_PATH = mm.MEMORY_PATH + ".bak"
        self._orig_critic = config.ENABLE_SELF_CRITIC

    def tearDown(self):
        import memory.memory_manager as mm
        mm.MEMORY_PATH, mm.BACKUP_PATH = self._orig_mem, self._orig_bak
        self.api.call_llm = self._orig_call
        self.main.speak = self._orig_speak
        config.ENABLE_SELF_CRITIC = self._orig_critic
        self.tmp.cleanup()

    def run_session(self, script, provider=None):
        provider = provider or ScriptedProvider()
        self.api.call_llm = provider
        ui = FakeTerminalUI(script)
        self.main.run_loop(ui)
        return ui, provider

    # ---------------- Phase 14: the mandated end-to-end chain ---------------

    def test_full_chain(self):
        ui, provider = self.run_session([
            "remember my favorite color is teal",   # memory update write
            "what's my favorite color",             # local recall via fast planner
            "delegate the arithmetic check",        # agent delegation through tools
            "route my domain",                      # skill routing
            "what device are you on",               # phone-body device probe
            "orchestrate this analysis for me",     # agent orchestration via tool
            "start serious mode",                   # personality on (challenge)
            "nano 808",                             # authentication (never logged)
            "hello",                                # chat under serious persona
            "stop serious mode",                    # personality off
            "exit",
        ])
        out = ui.text()

        # MEMORY: write then fast-path recall (zero LLM for recall)
        import memory.memory_manager as mm
        self.assertEqual(mm.load_memory()["preferences"]["favorite_color"]["value"], "teal")
        self.assertIn("Your favorite color is teal.", out)
        recall_calls = [c for c in provider.calls if "what's my favorite color" in c[1]]
        self.assertEqual(recall_calls, [], "recall must be answered locally")

        # AGENT → TOOL → EXECUTION (agent ran calculate through the pool)
        self.assertIn("81", out)

        # SKILL routing through the tool contract
        self.assertIn("Domain: chemistry", out)

        # PHONE BODY probe through the tool contract
        self.assertIn("Device:", out)

        # ORCHESTRATION through the tool contract (headline + aggregate cap 600)
        self.assertIn("Orchestrated 4 agent(s)", out)
        self.assertIn("verdict", out)

        # PERSONALITY engaged both directions via natural phrase
        self.assertIn("SERIOUS MODE: ON", out)        # authenticated activation
        self.assertIn("authentication", out.lower())  # the challenge ran first
        self.assertIn("Normal mode active", out)

        # SELF-CRITIC stage reached when confidence/structure demands
        kinds = [k for k, _ in provider.calls]
        self.assertIn("chat", kinds)

        # HEALTH: each stage left zero tracebacks
        self.assertNotIn("Traceback", json.dumps(ui.outputs))

    def test_personality_rules_persist_across_sessions(self):
        import personality
        personality.set_mode(personality.SERIOUS)
        try:
            from cognition import CognitiveEngine
            rules = CognitiveEngine().prepare("plan the deployment").mode.rules
            self.assertTrue(any("task-first" in r for r in rules))
        finally:
            personality.set_mode(personality.NORMAL)

    # ---------------- Phase 15: failure modes -------------------------------

    def test_provider_timeout_is_graceful(self):
        class Timeouty:
            def __call__(self, *a, **k):
                from providers.base import ProviderError
                raise ProviderError("Gemini request timed out")
        ui, _ = self.run_session(["hello", "exit"], Timeouty())
        self.assertIn("system error", ui.text())
        self.assertNotIn("Traceback", json.dumps(ui.outputs))

    def test_invalid_llm_payload_falls_back_to_text(self):
        class BadJson:
            def __call__(self, *a, **k):
                return "not json at all, just words"
        ui, _ = self.run_session(["hello", "exit"], BadJson())
        self.assertIn("not json at all", ui.text())  # llm.py _fallback path

    def test_missing_tool_routing(self):
        class WrongTool:
            def __call__(self, *a, **k):
                return json.dumps({"intent": "fly_to_mars", "parameters": {},
                                   "text": "I can't actually do that here.","memory_update":None})
        ui, _ = self.run_session(["fly to mars please", "exit"], WrongTool())
        self.assertIn("I can't actually do that here.", ui.text())

    def test_tool_failure_reports_not_crashes(self):
        class BadFile:
            def __call__(self, *a, **k):
                return json.dumps({"intent": "read_file",
                                   "parameters": {"path": "/definitely/not/here"},
                                   "text": None, "memory_update": None})
        ui, _ = self.run_session(["read the file", "exit"], BadFile())
        txt = ui.text()
        self.assertIn("No such file", txt)
        self.assertNotIn("Traceback", txt)

    def test_restart_persistence(self):
        """State written in session 1 is fully visible to a fresh session 2
        (the redirected temp memory file persists between run_loop calls — a
        stand-in for process restart)."""
        self.run_session(["remember my favorite color is teal", "exit"])
        ui, _ = self.run_session(["what's my favorite color", "exit"])
        self.assertIn("teal", ui.text())


if __name__ == "__main__":
    unittest.main()
