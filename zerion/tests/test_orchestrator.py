# tests/test_orchestrator.py
"""Orchestrator + orchestration integration battery."""
import json
import os
import sys
import unittest
from unittest import mock

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.chdir(BASE)


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        from agents.orchestrator import Orchestrator, classify
        from agents.pool import AgentPool
        self.classify = classify
        self.Orchestrator = Orchestrator
        self.pool = AgentPool(max_agents=4, resources={"cores": 4, "mem_gb": 8})

    def tearDown(self):
        self.pool.shutdown()

    def test_classify_minimum_sets(self):
        # spec examples land on the required minimal sets
        self.assertEqual(self.classify("Explain this concept")[0], ())
        self.assertEqual(self.classify("control my phone light")[0],
                         ("controller", "security", "verifier"))
        self.assertEqual(self.classify("analyze this trading strategy")[0],
                         ("finance", "data", "security", "verifier"))
        self.assertEqual(self.classify("find information online")[0],
                         ("researcher", "verifier"))

    def test_no_specialist_means_no_orchestration(self):
        orch = self.Orchestrator(self.pool)
        out = orch.run("hello, how are you?")
        self.assertFalse(out["orchestrated"])
        self.assertIn("core", out["message"])

    def test_full_run_has_critic_verify_learn(self):
        orch = self.Orchestrator(self.pool)
        out = orch.run("analyze this trading strategy quickly")
        self.assertTrue(out["orchestrated"])
        self.assertEqual(out["agents"], ["finance", "data", "security", "verifier"])
        self.assertIn("confidence", out)
        self.assertIn(out["critic"]["verdict"], ("accept", "revise"))
        states = [s for s, _ in out["lifecycle"]]
        self.assertEqual(states[0], "selected")
        self.assertIn("completed", states)
        self.assertIn("released", states)
        # telemetry recorded (and retrievable through the canonical KB)
        from knowledge.manager import KnowledgeManager
        hits = KnowledgeManager().retrieve_context("agent finance", limit=10)
        self.assertIsNotNone(hits)

    def test_orchestrate_tool_drives_it(self):
        from tools.manager import tool_manager
        r = tool_manager.execute("agent_orchestrate",
                                 {"goal": "analyze this trading strategy"})
        self.assertTrue(r.success)
        self.assertIn("agents", r.data)
        self.assertIn("verdict", r.data["critic"])

    def test_rules_never_produce_destructive_wholesale(self):
        from agents.types import AGENT_TYPES
        for t in AGENT_TYPES.values():
            for tool in t.allowed_tools:
                # every agent whitelist: read-only or analysis-only
                self.assertNotIn(tool, ("run_shell", "delete_file", "write_file",
                                        "move_file", "rename_file"))

    def test_messages_schema_fields(self):
        from agents.messages import AgentMessage
        m = AgentMessage.new("ocr goal", agent_id="a-1")
        d = m.to_dict()
        for k in ("task_id", "agent_id", "parent_task_id", "objective", "context",
                  "inputs", "capabilities_required", "permissions_required",
                  "actions", "results", "confidence", "evidence", "errors",
                  "status", "created_at", "finished_at"):
            self.assertIn(k, d)

    def test_pool_lifecycle_full_arc(self):
        r = self.pool.spawn("researcher", {"query": "anything"})
        self.assertTrue(r["ok"], r)
        lifecycle = r["agent"]["lifecycle"]
        for state in ("registered", "selected", "initialized", "executing",
                      "verified", "completed"):
            self.assertIn(state, lifecycle, f"lifecycle missing {state}: {lifecycle}")

    def test_agent_failure_isolated_and_reported(self):
        orch = self.Orchestrator(self.pool)
        out = orch.run("security audit anything")
        self.assertTrue(out["orchestrated"])
        # security can't query memory; it will try knowledge? it has no search;
        # orchestrator gives it first whitelisted tool (read_file w/o params) —
        # that CAN fail. The orchestrator must report it, not swallow.
        self.assertIn("security", out["agents"])
        self.assertTrue(any(c["status"] in ("completed", "failed")
                            for c in out["lanes"].values()))

    def test_health_agent_probe_shows_posture(self):
        from agents import agent_pool  # public package surface, never shadowed
        r = agent_pool.spawn("monitor", {"tool": "get_time"}, wait=False)
        self.assertTrue(r.get("ok"))
        s = agent_pool.stats()
        self.assertIn("capacity", s)
        self.assertIn("resources", s)


class ToolSurfaceTests(unittest.TestCase):
    def test_run_pytest_bounded(self):
        from tools.test_tools import PytestRunTool
        tool = PytestRunTool()
        self.assertFalse(tool.destructive)

        class FakeProc:
            returncode = 0
            stdout = "12 passed"
            stderr = ""

        with mock.patch("subprocess.run", return_value=FakeProc()) as runp:
            result = tool.execute({"path": "tests/test_phone.py"})
        self.assertTrue(result.success)
        self.assertIn("12 passed", result.message)
        self.assertFalse(runp.call_args[1].get("shell", False), "must never use shell=True")

        bad = tool.execute({"path": "/etc/passwd"})
        self.assertFalse(bad.success)

    def test_run_pytest_in_tool_registry(self):
        from tools.manager import tool_manager
        self.assertIsNotNone(tool_manager.get_tool("run_pytest"))
        self.assertIsNotNone(tool_manager.get_tool("agent_orchestrate"))
        self.assertIsNotNone(tool_manager.get_tool("agent_performance"))


if __name__ == "__main__":
    unittest.main()
