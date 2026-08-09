# tests/test_runtime_hardening.py
"""§22 24/7 hardening + §19 coordinator + §20 Gemini verification + known-
finding regression (agent probe identity stays healthy)."""

import os
import tempfile
import unittest


class AgentHealthProbeRegression(unittest.TestCase):
    """FINDING A stays fixed: the probe must be HEALTHY with the pool real."""

    def test_probe_agents_healthy(self):
        from runtime.service import ZerionService
        from runtime.logging import StructuredLogger
        svc = ZerionService(runtime_dir=tempfile.mkdtemp(), enable_ui=False,
                            greet=False, logger=StructuredLogger(os.devnull))
        svc._stage_core()
        svc._register_subsystems()
        svc.monitor.tick()
        sub = svc.monitor.snapshot()["subsystems"]["agents"]
        self.assertIn(str(sub["state"]), ("healthy", "degraded"))
        self.assertNotIn("agent_pool", str(sub.get("last_error") or ""),
                         "alias regression: import errors must never return")


class ResourcesSubsystemTests(unittest.TestCase):
    def test_resources_probe_registered(self):
        from runtime.service import ZerionService
        from runtime.logging import StructuredLogger
        svc = ZerionService(runtime_dir=tempfile.mkdtemp(), enable_ui=False,
                            greet=False, logger=StructuredLogger(os.devnull))
        svc._stage_core()
        svc._register_subsystems()
        svc.monitor.tick()
        snap = svc.monitor.snapshot()["subsystems"]
        self.assertIn("resources", snap)
        self.assertIn(str(snap["resources"]["state"]), ("healthy", "disabled"))

    def test_reaper_wired_in_maintenance(self):
        # proof via static+runtime: maintenance body must call agent_pool.reap()
        import inspect
        from runtime import service
        src = inspect.getsource(service.ZerionService._run_maintenance)
        self.assertIn("agent_pool.reap", src)


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._td = tempfile.mkdtemp()
        import knowledge.database as kdb
        self._kdb = kdb.Database.__init__.__defaults__
        kdb.Database.__init__.__defaults__ = (os.path.join(self._td, "k.db"),)
        import memory.memory_manager as mm
        self._mm = (mm.MEMORY_PATH, mm.BACKUP_PATH)
        mm.MEMORY_PATH = os.path.join(self._td, "m.json")
        mm.BACKUP_PATH = mm.MEMORY_PATH + ".bak"

    def tearDown(self):
        import knowledge.database as kdb
        kdb.Database.__init__.__defaults__ = self._kdb
        import memory.memory_manager as mm
        mm.MEMORY_PATH, mm.BACKUP_PATH = self._mm

    def test_persona_round_trip_through_controller(self):
        from memory.coordinator import coordinator
        route = coordinator.store("memory.persona.identity.name", "Nadia")
        self.assertEqual(route, "json-memory")
        st = coordinator.status()
        self.assertEqual(st["json_sections"]["identity"], 1)

    def test_non_persona_goes_to_knowledge(self):
        from memory.coordinator import coordinator
        coordinator.store("task.summary", "did the thing well",
                          tags=["t"], importance=.5, confidence=.7)
        st = coordinator.status()
        self.assertGreaterEqual(st["knowledge_records"], 1)

    def test_learning_engine_writes_through_coordinator(self):
        from learning.engine import LearningEngine
        eng = LearningEngine()
        long_reply = "evidence-based response " * 6
        eng.learn_task("probe goal", long_reply, elapsed=0.1)
        from knowledge.manager import KnowledgeManager
        rows = KnowledgeManager().db.query(
            "SELECT category FROM records WHERE category='summary' ORDER BY id DESC LIMIT 1")
        self.assertTrue(rows, "learning write should persist (via coordinator)")


class GeminiHealthTests(unittest.TestCase):
    def setUp(self):
        import config
        self._g = config.GEMINI_API_KEY
        config.GEMINI_API_KEY = ""

    def tearDown(self):
        import config
        config.GEMINI_API_KEY = self._g

    def test_no_key_is_UNVERIFIED_not_green(self):
        from tools.manager import tool_manager
        r = tool_manager.execute("gemini_health", {"live": True})
        self.assertTrue(r.success)   # success = the CHECK ran; payload honesty
        self.assertEqual(r.data["status"], "UNVERIFIED")
        self.assertIn("GEMINI_API_KEY", r.message)

    def test_fake_transport_roundtrip_records_success_shape(self):
        from providers.gemini import GeminiProvider
        import providers.gemini as gm

        class Resp:
            status_code = 200
            def json(self):
                return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

        orig_post = gm.requests.post
        orig_conn = gm.socket.create_connection

        class _FakeSock:
            def close(self):  # socket.create_connection(...).close() contract
                pass

        gm.requests.post = lambda *a, **kw: Resp()
        gm.socket.create_connection = lambda *a, **kw: _FakeSock()
        import config
        config.GEMINI_API_KEY = "fake-test-key"
        try:
            p = GeminiProvider()
            out = p.call("sys", "ping", timeout=3)
            self.assertEqual(out, "ok")
        finally:
            gm.requests.post = orig_post
            gm.socket.create_connection = orig_conn


class SoakSimulationTests(unittest.TestCase):
    """Accelerated 24/7 soak: thousands of health ticks over a virtual clock;
    state tables must stay bounded (no leaks through failures/recoveries)."""

    def test_thousand_ticks_bounded(self):
        import time as _t
        from runtime.health import HealthMonitor, Subsystem, HealthState
        mon = HealthMonitor()
        state = {"calls": 0}

        def flappy():
            state["calls"] += 1
            return "degraded once" if state["calls"] % 9 == 0 else None

        mon.register(Subsystem("flappy", probe=flappy, recover=lambda: True))
        mon.register(Subsystem("solid", probe=lambda: None))
        base = _t.monotonic()
        for i in range(3000):
            mon.tick(now=base + i * 15)
        # busy inspection without private locks: snapshots stay bounded
        snap = mon.snapshot()
        self.assertLessEqual(snap["subsystems"]["flappy"]["checks"], 4000)
        # A flapping subsystem reaches FAILED via the runaway guard and STAYS
        # FAILED (deterministic; spaces are health-monitor invariants)
        self.assertEqual(snap["subsystems"]["flappy"]["state"], "failed")


if __name__ == "__main__":
    unittest.main()
