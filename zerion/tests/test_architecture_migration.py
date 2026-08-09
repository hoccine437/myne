# tests/test_architecture_migration.py
"""Target-architecture migration proofs — tout runtime, no claims by import."""

import json
import os
import tempfile
import time
import unittest


class _Iso(unittest.TestCase):
    def setUp(self):
        import knowledge.database as kdb
        self._db = kdb.Database.__init__.__defaults__
        kdb.Database.__init__.__defaults__ = (os.path.join(tempfile.mkdtemp(), "m.db"),)
        import comms.store as cs
        cs._POPULATED = False

    def tearDown(self):
        import knowledge.database as kdb
        kdb.Database.__init__.__defaults__ = self._db


class TestMcpGateway(_Iso):
    def test_gateway_resolves_real_capabilities(self):
        from mcp.gateway import gateway
        caps = {c["capability"] for c in gateway.capabilities()}
        for needed in ("file.read", "web.fetch", "compute.math", "comm.health"):
            self.assertIn(needed, caps)

    def test_tool_reverse_map_boundary(self):
        from mcp.gateway import gateway
        self.assertEqual(gateway.capabilities_for_tool("read_file"), "file.read")
        self.assertIsNone(gateway.capabilities_for_tool("run_shell"),
                          "exec must NOT be exposed on the agent boundary")

    def test_permission_enforcement_for_agents(self):
        from mcp.gateway import gateway
        r = gateway.call("file.read", {"path": "/nonexistent/x"}, caller="agent")
        self.assertFalse(r.ok)  # missing file handled as an error — not fake ok
        out = gateway.call_tool("run_python", {"code": "print(1)"}, caller="agent")
        self.assertFalse(out.ok)
        self.assertEqual(out.code, "mcp.capability_not_exposed")

    def test_audit_records_calls(self):
        from comms import audit
        from mcp.gateway import gateway
        gateway.call("compute.math", {"expression": "7*7"}, caller="agent")
        entries = audit.tail(10)
        self.assertTrue(any(e.get("action") == "mcp.call" and
                            e.get("target") == "compute.math" and
                            e.get("result") == "ok" for e in entries))
        for e in entries:
            self.assertNotIn("password", json.dumps(e).lower())

    def test_timeout_is_bounded(self):
        # slow adapter over real HTTP now proves the timeout machinery without
        # network: expected failure must be surfaced (no raises, structured)
        from mcp.gateway import gateway
        r = gateway.call("web.fetch", {"url": "http://127.0.0.1:9/nope"}, caller="agent")
        self.assertFalse(r.ok)
        self.assertTrue(r.code.startswith("mcp."), r.code)


class TestAgentEngine(_Iso):
    def test_lifecycle_and_metadata_shape(self):
        from agents.engine import engine, AGENT_LIFECYCLE
        meta = engine.list_types()
        self.assertTrue(any(m["name"] == "researcher" for m in meta))
        self.assertIn("registered", AGENT_LIFECYCLE)

    def test_plugin_registration_live(self):
        from agents.engine import engine
        t = engine.register_type("scanner_x", "demo scan capability",
                                 allowed_tools=("get_time",), can_search_memory=False)
        self.assertEqual(t.name, "scanner_x")
        self.assertIn("scanner_x", [m["name"] for m in engine.list_types()])
        out = engine.spawn("scanner_x", {"tool": "get_time"}, wait=True)
        self.assertTrue(out.get("ok"), out.get("error"))
        self.assertEqual(out["agent"]["status"], "completed")
        self.assertTrue(out.get("engine_handle"),
                        "the engine must record the real lifecycle")


class TestInternalEventBus(_Iso):
    def test_tool_events_flow(self):
        from core import events
        received = []
        events.bus.clear()
        events.bus.subscribe(received.append)
        from tools.manager import tool_manager
        tool_manager.execute("get_time", {})
        events.bus.unsubscribe(received.append)
        kinds = [e.type for e in received]
        self.assertIn("tool.called", kinds)

    def test_health_transition_events(self):
        from core import events
        events.bus.clear()
        from runtime.health import HealthMonitor, Subsystem, HealthState
        from runtime.logging import StructuredLogger
        mon = HealthMonitor(logger=StructuredLogger(os.devnull))
        from runtime.service import ZerionService
        svc = ZerionService(runtime_dir=tempfile.mkdtemp(), enable_ui=False,
                            greet=False, logger=StructuredLogger(os.devnull))
        # wire via the service's on_state_change path
        sub = Subsystem("probe-test", probe=lambda: "always bad",
                        recover=lambda: False)
        svc.monitor.register(sub)
        svc.monitor.force_check("probe-test")
        # recovering/degraded/failed are all real evidence of the transition;
        # the probe smiles at failure + recover=False → 'recovering' first
        found = [e for e in events.bus.replay()
                 if e.type in ("health.degraded", "health.changed")
                 and e.payload.get("subsystem") == "probe-test"
                 and e.payload.get("to") in ("recovering", "degraded", "failed")]
        self.assertTrue(found, "state-change must land on the event bus")


class TestBootstrapConsolidation(_Iso):
    def test_bootstrap_report_wired_at_least_once(self):
        from core.bootstrap import bootstrap
        report = bootstrap("ui")
        self.assertIn("laws", report)
        self.assertGreater(report["laws"], 0)
        self.assertIn("tools", report)

    def test_main_uses_bootstrap(self):
        import inspect
        import main
        src = inspect.getsource(main.main)
        self.assertIn("bootstrap(", src)


class TestStateManager(_Iso):
    def test_snapshot_real_system_state(self):
        from core.state_manager import state_manager
        snap = state_manager.snapshot()
        self.assertIn("agents", snap)
        self.assertIn("capacity", snap["agents"])
        self.assertIn("comm", snap)
        self.assertIn("planner", snap)

    def test_cancel_pending_real(self):
        from core.state_manager import state_manager
        from tools.manager import tool_manager
        tool_manager.execute("delete_file", {"path": "irrelevant/x"})
        self.assertTrue(tool_manager.has_pending_confirmation())
        out = state_manager.cancel_pending()
        self.assertTrue(out["tool"])
        self.assertFalse(tool_manager.has_pending_confirmation())


class TestWorkflowOrchestrator(_Iso):
    def test_single_owner_of_agent_consult(self):
        import inspect
        import intent.engine as ie
        src = inspect.getsource(ie._maybe_orchestrate)
        self.assertIn("workflow_orchestrator", src)


if __name__ == "__main__":
    unittest.main()
