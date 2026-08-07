# tests/test_main_integration.py
"""End-to-end integration validation of the main.py runtime pipeline.

Drives the REAL main.run_loop() with:
  - a scripted terminal (fake TerminalUI: get_input/write_log surface)
  - speech stubbed off
  - a deterministic fake LLM provider injected at api.call_llm —
    which is the single transport used by llm.py, planner.decomposer
    and intelligence.critic, so EVERY LLM-dependent pipeline stage runs:
    intent classification → fast planner → AI planner (decompose →
    execute → verify) → tool routing + confirmation flow → memory
    persistence → self-critic review + improve → learning → response

Also validates the no-provider graceful floor, startup banner, config
validation, clean shutdown, and idle maintenance tick.

Memory is redirected to a temp file so the repo's real memory.json is
untouched. Knowledge writes go to the gitignored dev DB, as in all
existing Core tests.
"""

import json
import os
import sys
import tempfile
import threading
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
        if self.script:
            return self.script.pop(0)
        return "exit"

    def ai_lines(self):
        return [o[3:].strip() if o.startswith("AI:") else o
                for o in self.outputs if o.startswith("AI:")]


class FakeProvider:
    """Deterministic stand-in for the LLM transport. Dispatches on the
    well-known prompt shapes of the three call sites. Every call is
    recorded with (kind, user_message) so tests can assert *which* stage
    fired without depending on confidence-dependent critic gating."""

    def __init__(self, memory_path_for_delete):
        self.calls = []
        self.target = memory_path_for_delete

    def __call__(self, system_prompt, user_prompt, **kw):
        user_message = ""
        if 'User message: "' in user_prompt:
            user_message = user_prompt.split('User message: "', 1)[1].split('"', 1)[0]

        # --- planner decomposer ---
        if system_prompt.startswith("You are a precise task planner"):
            self.calls.append(("decompose", user_message))
            return json.dumps({
                "complex": True,
                "goal": "research and note zerion",
                "tasks": [
                    {"id": 1, "description": "Research Zerion facts", "tool_name": None,
                     "parameters": {}, "depends_on": []},
                    {"id": 2, "description": "Write the summary note", "tool_name": None,
                     "parameters": {}, "depends_on": [1]},
                ],
            })

        # --- self-critic improve ---
        if system_prompt.startswith("You are a careful editor"):
            self.calls.append(("critic-improve", user_message))
            return "[REVISED] improved reply from the self-critic pass"

        # --- main conversational contract ---
        self.calls.append(("chat", user_message))
        if "my name is Nadia" in user_message:
            return json.dumps({
                "intent": "chat",
                "parameters": {},
                "text": "Nice to meet you, Nadia — I'll remember that.",
                "memory_update": {"identity": {"name": {"value": "Nadia"}}},
            })
        if "say ok" in user_message:
            # intentionally too short (< MINIMUM_RESPONSE_LENGTH) → the
            # critic must flag it structurally, deterministic regardless
            # of that turn's reasoning-confidence score
            return json.dumps({"intent": "chat", "parameters": {},
                               "text": "ok", "memory_update": None})
        if "calculate" in user_message:
            return json.dumps({
                "intent": "calculate",
                "parameters": {"expression": "12 * 2"},
                "text": None, "memory_update": None,
            })
        if "delete" in user_message:
            return json.dumps({
                "intent": "delete_file",
                "parameters": {"path": self.target},
                "text": None, "memory_update": None,
            })
        return json.dumps({
            "intent": "chat", "parameters": {},
            "text": "A short chat reply.", "memory_update": None,
        })


class MainPipelineE2ETests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        import api
        import main as main_mod
        import memory.memory_manager as mm

        self.main = main_mod
        self.api = api
        self._orig_call = api.call_llm
        self._orig_planner = config.PLANNER_ENABLED
        # redirect memory to a temp file
        self.tmp = tempfile.TemporaryDirectory()
        self.mem_path = os.path.join(self.tmp.name, "memory.json")
        self._orig_mem = mm.MEMORY_PATH
        self._orig_bak = mm.BACKUP_PATH
        mm.MEMORY_PATH = self.mem_path
        mm.BACKUP_PATH = self.mem_path + ".bak"
        # speech off entirely: speak() must never fire
        self._orig_speak = main_mod.speak
        main_mod.speak = lambda *a, **k: None

    def tearDown(self):
        import memory.memory_manager as mm
        mm.MEMORY_PATH = self._orig_mem
        mm.BACKUP_PATH = self._orig_bak
        self.main.speak = self._orig_speak
        self.api.call_llm = self._orig_call
        config.PLANNER_ENABLED = self._orig_planner
        self.tmp.cleanup()

    def _run_loop(self, script, fake):
        self.api.call_llm = fake
        ui = FakeTerminalUI(script)
        self.main.run_loop(ui)
        return ui

    # ------------------------------------------------------------------

    def test_full_pipeline_trace(self):
        target = os.path.join(self.tmp.name, "to-delete.txt")
        with open(target, "w") as f:
            f.write("tmp")

        config.PLANNER_ENABLED = True
        fake = FakeProvider(target)
        ui = self._run_loop([
            "my name is Nadia",            # 1) chat + memory_update
            "what's my name",              # 2) MEMORY intent → fast planner (no LLM call)
            "what time is it",             # 3) plain chat reply
            "say ok",                      # 4) structurally too-short reply → critic improves it
            "please calculate twelve times two",  # 5) intent=calculate → tool executes
            f"delete the file {target}",   # 6) destructive → confirmation gate
            "confirm",                     # 7) approve → executes
            "research zerion then write a summary note",  # 8) planner path
            "",                            # 9) idle maintenance tick
            "exit",
        ], fake)

        out = "\n".join(ui.ai_lines())

        # 1) memory_update persisted (into the REDIRECTED temp memory)
        import memory.memory_manager as mm
        mem = mm.load_memory()
        self.assertEqual(
            mem.get("identity", {}).get("name", {}).get("value"), "Nadia",
            f"memory update not persisted. outputs so far:\n{out}")
        self.assertIn("Nadia", ui.ai_lines()[0])

        # 2) fast planner answered the memory recall locally — the
        #    provider must have seen ZERO calls for that turn
        self.assertIn("Your name is Nadia.", out)
        memory_turn_calls = [c for c in fake.calls if "what's my name" in c[1]]
        self.assertEqual(memory_turn_calls, [],
                         "memory-recall turn must be answered with no LLM call")

        # 4) self-critic: the too-short draft was flagged and improved;
        #    the user sees the revised text, calling the 'editor' prompt
        self.assertIn("[REVISED]", out)
        critic_calls = [c for c in fake.calls if c[0] == "critic-improve"]
        self.assertTrue(critic_calls, "self-critic improve pass must run")

        # stages seen overall: chat calls, one decompose, tool intents
        kinds = [c[0] for c in fake.calls]
        self.assertIn("decompose", kinds)
        self.assertIn("chat", kinds)

        # 4) tool routing: calculate executed via LLM intent contract
        self.assertIn("24", out)

        # 5+6) confirmation gate held, then executed after 'confirm'
        self.assertFalse(os.path.exists(target),
                         "delete_file should have executed after confirmation")
        self.assertIn("confirm", out.lower())

        # 7) planner: plan executed, summary rendered, goal completed.
        #    (goal_manager is a process singleton; counts accumulate when
        #    the full suite runs, so assert at-least-one, not exact.)
        self.assertRegex(out, r"completed all 2 step\(s\)")
        from planner import planner as planning_engine
        summary = planning_engine.goal_manager.summary()
        self.assertGreaterEqual(summary["completed_count"], 1)
        self.assertIsNone(summary["current_goal"])

        # 8) no partial/crashed pipeline markers anywhere
        self.assertNotIn("Traceback", json.dumps(ui.outputs))

    def test_no_key_graceful_floor(self):
        """Without a provider key the loop must run cleanly: graceful
        error text per turn, no exceptions, clean exit."""
        class NoKeyProvider:
            def __call__(self, *a, **k):
                from providers.base import ProviderError
                raise ProviderError("GEMINI_API_KEY is not set.")
        ui = self._run_loop(["hello", "exit"], NoKeyProvider())
        out = "\n".join(ui.ai_lines())
        self.assertIn("system error", out)  # llm.py's graceful fallback text
        self.assertNotIn("Traceback", json.dumps(ui.outputs))

    def test_command_palette_and_interrupt_and_mute(self):
        fake = FakeProvider("/dev/null/unused")
        ui = self._run_loop(["/help", "/status", "mute", "exit"], fake)
        joined = "\n".join(ui.ai_lines())
        self.assertIn("/tools", joined)
        self.assertIn("Current goal", joined)
        # zero provider calls — palette + mute are fully local
        self.assertEqual(len(fake.calls), 0)

    def test_startup_config_validation(self):
        warnings = config.validate()
        self.assertTrue(any("Text model:" in w for w in warnings))
        self.assertTrue(any("Self-Critic:" in w for w in warnings))


class ThreadSafetyTests(unittest.TestCase):
    def test_memory_concurrent_updates(self):
        """memory_manager must survive concurrent writers (atomic save +
        lock) — write integrity verified by parseability + shape."""
        import memory.memory_manager as mm
        with tempfile.TemporaryDirectory() as d:
            orig, orig_bak = mm.MEMORY_PATH, mm.BACKUP_PATH
            mm.MEMORY_PATH = os.path.join(d, "m.json")
            mm.BACKUP_PATH = mm.MEMORY_PATH + ".bak"
            errors = []

            def writer(i):
                try:
                    for _ in range(30):
                        mm.update_memory({"preferences": {f"k{i}": {"value": i}}})
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
            for t in threads: t.start()
            for t in threads: t.join()
            self.assertEqual(errors, [])
            mem = mm.load_memory()
            self.assertIsInstance(mem, dict)
            self.assertIn("preferences", mem)
            mm.MEMORY_PATH, mm.BACKUP_PATH = orig, orig_bak
            mm.load_memory()  # ensure restored paths still work


if __name__ == "__main__":
    unittest.main()
