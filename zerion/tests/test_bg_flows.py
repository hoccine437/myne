# tests/test_bg_flows.py
"""Authorized background communication workflows (explicit authorization
objects) + constitution expansion enforcement. Offline hermetic."""

import json
import os
import tempfile
import time
import unittest


def _msg(platform="telegram", account="bot", sender="amina",
         content="did it work?", cid="777", ts=None):
    from comms.models import UnifiedMessage
    return UnifiedMessage(platform=platform, account=account, sender=sender,
                          content=content, conversation_id=cid,
                          timestamp=ts or time.time())


class Guard(unittest.TestCase):
    def setUp(self):
        import knowledge.database as kdb
        self._old = kdb.Database.__init__.__defaults__
        kdb.Database.__init__.__defaults__ = (os.path.join(tempfile.mkdtemp(), "b.db"),)
        import comms.store as cs
        cs._POPULATED = False
        import config
        self._c = config
        self._saved = {k: getattr(config, k) for k in (
            "COMM_ENABLED", "AUTOPILOT_ENABLED", "COMM_DEFAULT_LEVEL",
            "COMM_TRUSTED_RAW", "TELEGRAM_BOT_TOKEN", "GEMINI_API_KEY")}
        config.COMM_ENABLED = True
        config.AUTOPILOT_ENABLED = True
        config.COMM_DEFAULT_LEVEL = 2
        config.COMM_TRUSTED_RAW = "[]"
        config.GEMINI_API_KEY = ""
        from comms import overrides
        overrides.resume()

    def tearDown(self):
        import knowledge.database as kdb
        kdb.Database.__init__.__defaults__ = self._old
        for k, v in self._saved.items():
            setattr(self._c, k, v)
        from comms import overrides
        overrides.resume()


class TestFlowObjects(Guard):
    def test_start_scoped_expiring(self):
        from comms import bgworkflows
        flow = bgworkflows.start("instagram", scope="messages", ttl_s=3600)
        self.assertEqual(flow["status"], "active")
        self.assertEqual(flow["platform"], "instagram")
        self.assertEqual(flow["authorization_source"], "user-command")
        self.assertGreater(flow["expires_at"], time.time() + 3500)
        self.assertIn("draft", flow["allowed_actions"])

    def test_stop_immediate_and_idempotent(self):
        from comms import bgworkflows
        bgworkflows.start("instagram", ttl_s=3600)
        self.assertEqual(bgworkflows.stop(platform="instagram"), 1)
        self.assertEqual(bgworkflows.stop(platform="instagram"), 0)
        self.assertFalse(bgworkflows.active())

    def test_expiry_auto_deactivates(self):
        from comms import bgworkflows
        flow = bgworkflows.start("telegram", ttl_s=-1)  # already expired
        self.assertFalse(bgworkflows.active())
        got = bgworkflows.get(flow["flow_id"])
        self.assertEqual(got["status"], "expired")

    def test_covers_scoping(self):
        from comms import bgworkflows
        bgworkflows.start("instagram", account="me", ttl_s=3600)
        self.assertIsNotNone(bgworkflows.covers("instagram", "me"))
        self.assertIsNone(bgworkflows.covers("telegram", ""))
        self.assertIsNone(bgworkflows.covers("instagram", "other-account"))


class TestFlowGate(Guard):
    def test_no_flow_means_observe_only(self):
        from comms.autopilot import process_inbound
        out = process_inbound(_msg(content="reply please?"))
        self.assertEqual(out["outcome"], "observed-no-flow")

    def test_flow_enables_pipeline_then_stop_disables(self):
        from comms import bgworkflows, conversation_state, quality
        from comms.autopilot import process_inbound
        from comms.registry import connectors
        from comms.connectors.telegram import TelegramConnector
        self._c.TELEGRAM_BOT_TOKEN = "t:x"
        connectors.inject(TelegramConnector(http=lambda u, d:
                                            {"ok": True, "result": []}))
        conversation_state.touch("telegram", "bot", "777", sender="amina", topic="ops")
        quality.set_shadow("telegram", "graduated")
        self._c.COMM_DEFAULT_LEVEL = 2   # ladder says confirm → parks for approval
        bgworkflows.start("telegram", account="bot", ttl_s=3600)
        out = process_inbound(_msg(content="status update please?"))
        self.assertEqual(out["outcome"], "approval-parked", out)
        # stop → the same message shape now only observes
        bgworkflows.stop(platform="telegram")
        out2 = process_inbound(_msg(content="another status please?"))
        self.assertEqual(out2["outcome"], "observed-no-flow")


class TestFlowCommands(Guard):
    def test_command_handshake_ar(self):
        from intent import commands
        r1 = commands.handle("رد على الناس في انستغرام", None, {})
        self.assertIn("instagram", r1.lower())
        self.assertIn("confirm", r1.lower())
        r2 = commands.handle("confirm", None, {})
        self.assertIn("ACTIVE", r2)
        from comms import bgworkflows
        self.assertTrue(bgworkflows.active())

    def test_command_cancel(self):
        from intent import commands
        commands.handle("reply to people on instagram", None, {})
        r = commands.handle("actually no", None, {})
        self.assertIn("Cancelled", r)
        from comms import bgworkflows
        self.assertFalse(bgworkflows.active())

    def test_stop_command(self):
        from comms import bgworkflows
        from intent import commands
        bgworkflows.start("instagram", ttl_s=3600)
        r = commands.handle("stop instagram", None, {})
        self.assertIn("Stopped 1", r)

    def test_estop_all_command(self):
        from intent import commands
        r = commands.handle("stop all communication", None, {})
        from comms.overrides import is_estopped, is_paused
        self.assertIn("stopped", r.lower())
        self.assertTrue(is_estopped())
        # resume is trust-forward: must require tool confirmation
        r2 = commands.handle("resume communication", None, {})
        self.assertIn("confirm", r2.lower())
        from tools.manager import tool_manager
        done = tool_manager.confirm_pending()
        self.assertTrue(done.success)
        self.assertFalse(is_paused())


class TestConstitutionExtended(Guard):
    def test_new_laws_parse_and_load(self):
        from constitution.constitution import ConstitutionEngine
        laws = {l.id: l for l in ConstitutionEngine.load()}
        for lid in ("COM-001", "COM-002", "COM-003", "COM-004", "COM-005",
                    "COM-006", "COM-007", "COM-008", "COM-009", "COM-010",
                    "COM-011", "COM-012", "AUT-001", "AUT-002", "AUT-003",
                    "BGS-001", "BGS-002"):
            self.assertIn(lid, laws)
            self.assertGreater(laws[lid].priority, 0)

    def test_original_laws_untouched(self):
        from constitution.constitution import ConstitutionEngine
        laws = {l.id: l for l in ConstitutionEngine.load()}
        for lid in ("CORE-001", "SEC-001", "SEC-002", "EVO-001", "EMR-001",
                    "MEM-001", "CAP-001", "REA-001", "REA-002", "REA-003"):
            self.assertIn(lid, laws)

    def test_enforcement_hooks_reference_real_gates(self):
        # spot-map law → code gate (the map must stay true)
        import inspect
        from comms import decision, overrides, ratelimit, events, loopguard
        from comms import engine
        src_dec = inspect.getsource(decision.evaluate)
        self.assertIn("firewall.inspect", src_dec)          # COM-007
        self.assertIn("conv_belongs", src_dec)              # COM-003
        self.assertIn("serious_active", src_dec)            # AUT-002
        src_eng = inspect.getsource(engine.send_draft)
        self.assertIn("is_estopped", src_eng)               # COM-009
        self.assertIn("claim_action", src_eng)              # COM-005
        self.assertIn("rail", src_eng)                      # COM-006 + ratelimit
        src_ap = inspect.getsource(  # COM-001/002: flow gate
            __import__("comms.autopilot", fromlist=["process_inbound"]).process_inbound)
        self.assertIn("COMM_REQUIRE_FLOW", src_ap)

    def test_health_snapshot_writer(self):
        from comms import health
        snap = health.write("active", queue_depth=0, workflows_active=1)
        self.assertEqual(snap["service"], "active")
        self.assertEqual(snap["workflows_active"], 1)
        back = health.read()
        self.assertEqual(back["service"], "active")


if __name__ == "__main__":
    unittest.main()
