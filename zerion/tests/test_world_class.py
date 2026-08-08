# tests/test_world_class.py
"""World-class capability upgrade battery: decisions, context manager,
multimodal chain, meta-intelligence, benchmarks, research orchestration."""

import base64
import json
import os
import sys
import tempfile
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.chdir(BASE)


class DecisionIntelligenceTests(unittest.TestCase):
    def test_structured_decision(self):
        from cognition.decisions import decide
        d = decide("should I rewrite the auth module?",
                   [{"name": "rewrite", "cost": .9, "risk": .8, "benefit": .9, "reversible": False},
                    {"name": "patch", "cost": .2, "risk": .2, "benefit": .5, "reversible": True}],
                   evidence=["tests pass on patch branch"])
        self.assertIn(d.chosen, ("patch", "rewrite"))
        self.assertLessEqual(d.confidence, 0.9)
        self.assertGreaterEqual(d.confidence, 0.25)
        self.assertTrue(d.evidence)
        self.assertTrue(d.alternatives)

    def test_intent_detection(self):
        from cognition.decisions import is_decision_task
        self.assertTrue(is_decision_task("Should I use Redis or SQLite?"))
        self.assertFalse(is_decision_task("open the file notes.txt"))

    def test_defaults_never_invent_data(self):
        from cognition.decisions import decide
        d = decide("risky move?")
        self.assertTrue(
            "discovered-by-defect" in d.reason or "bounded default option" in d.reason)


class ContextManagerTests(unittest.TestCase):
    def test_budget_and_priority(self):
        from cognition.context import assemble
        block = {
            "user_name": "Nadia",
            "retrieved_knowledge": "k" * 5000,   # huge: must compress
            "reasoning_mode": "research",
            "_pending_intent": "save_notes",
            "zz_unknown": "x" * 500,             # unknown keys get room, trimmed last
        }
        out = assemble(block, budget=2000)
        self.assertIn("user_name: Nadia", out)
        self.assertIn("_pending_intent: save_notes", out)
        self.assertIn("reasoning_mode: research", out)
        self.assertIn("compressed", out)
        self.assertLessEqual(len(out), 2400)  # budget + slack for label

    def test_llm_prompt_uses_context_manager(self):
        import json as _json
        from llm import get_llm_output
        import api
        calls = []
        orig = api.call_llm
        api.call_llm = lambda s, u, **kw: (calls.append(u), '"text":"ok"')[-1]
        try:
            get_llm_output("hello", {"retrieved_knowledge": "x" * 9000,
                                     "user_name": "Nadia"})
        finally:
            api.call_llm = orig
        body = calls[0]
        self.assertIn("user_name: Nadia", body)
        self.assertLess(len(body), 9000 + 4000)


class MultimodalChainTests(unittest.TestCase):
    def test_gemini_payload_has_inline_image(self):
        import providers.gemini as gemini
        from unittest import mock
        captured = {}

        def fake_post(url, headers=None, params=None, json=None, timeout=None):
            captured["json"] = json
            r = mock.Mock(); r.status_code = 200
            r.json = lambda: {"candidates": [{"content": {"parts": [{"text": "it shows a sunrise"}]}}]}
            return r

        with mock.patch.object(__import__("socket"), "create_connection",
                               return_value=mock.Mock(close=lambda: None)), \
             mock.patch("requests.post", side_effect=fake_post):
            orig = __import__("config").GEMINI_API_KEY
            __import__("config").GEMINI_API_KEY = "k"
            out = gemini.GeminiProvider().call(
                "s", "u", timeout=5, image_b64=base64.b64encode(b"\xff\xd8\xff").decode(),
                image_mime="image/jpeg")
            __import__("config").GEMINI_API_KEY = orig
        self.assertEqual(out, "it shows a sunrise")
        parts = captured["json"]["contents"][0]["parts"]
        self.assertEqual(parts[0]["inline_data"]["mime_type"], "image/jpeg")
        self.assertTrue(parts[0]["inline_data"]["data"])

    def test_llm_forwards_image(self):
        from llm import get_llm_output
        import api
        seen = {}
        orig = api.call_llm

        def fake(sys_p, user_p, **kw):
            seen.update(kw)
            return json.dumps({"intent": "chat", "text": "I see a diagram.", "parameters": {},
                               "memory_update": None})
        api.call_llm = fake
        try:
            out = get_llm_output("what's this?", {"user_name": "n"},
                                 image_b64=base64.b64encode(b"123").decode(),
                                 image_mime="image/png")
        finally:
            api.call_llm = orig
        self.assertEqual(seen.get("image_mime"), "image/png")
        self.assertIn("diagram", out["text"])


class MetaIntelligenceTests(unittest.TestCase):
    def test_meta_answers_from_live_state(self):
        from meta import answer
        text = answer("what do you know and what can you do?")
        self.assertIsNotNone(text)
        self.assertIn("tool(s)", text)
        self.assertIn("agent types", text)

    def test_meta_fast_path(self):
        from intent.fast_planner import try_handle
        from intent.classifier import classify
        c, _ = classify("what do you know about me"), None
        result = try_handle(classify("what can you do", []), "what can you do", {})
        self.assertIsNotNone(result)
        self.assertIn("tool(s)", result["text"])


class BenchmarksTests(unittest.TestCase):
    def test_benchmark_runs_all_lenses(self):
        import benchmarks
        r = benchmarks.run_all()
        for lens in ("reasoning", "decision", "tool", "memory",
                     "orchestration", "offline_intent", "constitution"):
            self.assertIn(lens, r["results"])
        self.assertTrue(r["results"]["reasoning"]["valid"])
        self.assertTrue(r["results"]["decision"]["deterministic"])
        self.assertTrue(r["all_ok"])


class ResearchLaneTests(unittest.TestCase):
    def test_research_selection_lanes(self):
        from agents.orchestrator import Orchestrator
        from agents.pool import AgentPool
        pool = AgentPool(max_agents=4, resources={"cores": 4, "mem_gb": 8})
        orch = Orchestrator(pool)
        out = orch.run("research and compare the sources")
        self.assertTrue(out["orchestrated"])
        self.assertIn("verifier", out["agents"])
        self.assertIn("critic", out)
        pool.shutdown()


if __name__ == "__main__":
    unittest.main()
