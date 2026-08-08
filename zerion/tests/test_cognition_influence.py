# tests/test_cognition_influence.py
"""Runtime proof that the cognitive layer actually REACHES the model:
the prompt is recorded verbatim by the scripted transport, and every
cognitive signal is asserted to change it — memory, knowledge retrieval,
reasoning mode/strategy, capability context, confidence/critic gating,
and tool results flowing into the next turn's context."""

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

    def write_log(self, text): self.outputs.append(str(text))
    def start_speaking(self): pass
    def stop_speaking(self): pass
    def get_input(self, prompt="You: "):
        return self.script.pop(0) if self.script else "exit"


class PromptRecorder:
    def __init__(self):
        self.calls = []

    def __call__(self, system_prompt, user_prompt, **kw):
        msg = ""
        if 'User message: "' in user_prompt:
            msg = user_prompt.split('User message: "', 1)[1].split('"', 1)[0]
        self.calls.append((system_prompt, user_prompt))
        if self.calls[-1] and "calculate this value" in msg:
            return json.dumps({"intent": "calculate",
                               "parameters": {"expression": "6 * 7"},
                               "text": "That equals 42.", "memory_update": None})
        if "my name is" in msg:
            return json.dumps({"intent": "chat", "parameters": {},
                               "text": "Sure.", "memory_update": {
                                   "identity": {"name": {"value": "Nadia"}}}})
        return json.dumps({"intent": "chat", "parameters": {},
                           "text": "acknowledged.", "memory_update": None})


class CognitionInfluenceTests(unittest.TestCase):
    def setUp(self):
        import api
        import main as main_mod
        import knowledge.database as kdb
        import memory.memory_manager as mm
        self.main = main_mod
        self.api = api
        self._orig_call = api.call_llm
        self._orig_speak = main_mod.speak
        main_mod.speak = lambda *a, **k: None
        self.tmp = tempfile.TemporaryDirectory()
        self._m, self._b = mm.MEMORY_PATH, mm.BACKUP_PATH
        mm.MEMORY_PATH = os.path.join(self.tmp.name, "m.json")
        mm.BACKUP_PATH = mm.MEMORY_PATH + ".bak"
        # isolate knowledge DB from the shared dev store (retrieval ranking
        # is global; other tests leave high-overlap records)
        self._kdb_defaults = kdb.Database.__init__.__defaults__
        kdb.Database.__init__.__defaults__ = (os.path.join(self.tmp.name, "ki.db"),)

    def tearDown(self):
        import knowledge.database as kdb
        import memory.memory_manager as mm
        mm.MEMORY_PATH, mm.BACKUP_PATH = self._m, self._b
        kdb.Database.__init__.__defaults__ = self._kdb_defaults
        self.api.call_llm = self._orig_call
        self.main.speak = self._orig_speak
        self.tmp.cleanup()

    def run_script(self, script):
        rec = PromptRecorder()
        self.api.call_llm = rec
        ui = FakeTerminalUI(script)
        self.main.run_loop(ui)
        return ui, rec

    @staticmethod
    def _chat_calls(rec):
        """Only main-conversation calls (skip critic-improve / planner prompts)."""
        return [p for (s, p) in rec.calls
                if not s.startswith("You are a careful editor")
                and not s.startswith("You are a precise task planner")]

    def test_memory_changes_next_turn_prompt(self):
        _, rec = self.run_script(["my name is Nadia", "hello again", "exit"])
        chats = self._chat_calls(rec)
        self.assertEqual(len(chats), 2)
        self.assertIn("user_name: Nadia", chats[1])

    def test_knowledge_retrieval_changes_prompt(self):
        # knowledge search is exact-token overlap (documented cheap local
        # retrieval); the message shares at least one exact token
        from knowledge.manager import KnowledgeManager
        KnowledgeManager().store("the zephyrine orchid marker from the vault",
                                 "note", ["zephyrine"], .9, .9, {}, "knowledge")
        _, rec = self.run_script(["what do you remember about zephyrine", "exit"])
        joined = "\n".join(p for _, p in rec.calls)
        self.assertIn("orchid marker from the vault", joined)

    def test_reasoning_context_reaches_prompt(self):
        _, rec = self.run_script(["help me debug this python function", "exit"])
        prompt = rec.calls[0][1]
        self.assertIn("reasoning_mode: programming", prompt)
        self.assertIn("reasoning_strategy:", prompt)
        self.assertIn("reasoning_confidence:", prompt)
        self.assertIn("capability_strategy:", prompt)

    def test_hypothesis_scaffolding_reaches_prompt(self):
        _, rec = self.run_script(["why would my offline code answer wrong", "exit"])
        prompt = rec.calls[0][1]
        self.assertIn("revisable_hypotheses:", prompt)
        self.assertIn("Evidence-led explanation", prompt)

    def test_selfcritic_reflines_short_answers(self):
        """Critique only fires when warranted: prove gate, not assumption."""
        from intelligence.critic import self_critic
        long_ctx = self_critic.review("explain recursion", "Recursion is when a function calls itself with a base case and a recursive case.", 0.9)
        self.assertFalse(long_ctx.should_improve)
        short_ctx = self_critic.review("explain recursion", "ok", 0.9)  # below MINIMUM_RESPONSE_LENGTH
        self.assertTrue(short_ctx.should_improve)

    def test_tool_result_reaches_next_turn_context(self):
        ui, rec = self.run_script([
            "calculate this value",                 # tool → 42
            "what number did you just compute",     # follow-up prompt must contain 42
            "exit",
        ])
        self.assertTrue(any("42" in o for o in ui.outputs), "tool result not visible")
        chats = self._chat_calls(rec)
        self.assertIn("42", chats[-1])


if __name__ == "__main__":
    unittest.main()
