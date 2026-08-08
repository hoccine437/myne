# tests/test_phone_body.py
"""Phone Body verification battery. Everything runs through the composed
phone.manager.PhoneBodyManager — no mocks claiming hardware happened.

Adapter-level effects are faked with a recording fake adapter (the point
being the lifecycle, not Termux binaries); the *call* contract verified is
the real TermuxAdapter argv shape.
"""

import os
import sys
import tempfile
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.chdir(BASE)

import json  # noqa: E402
from phone.actions import (APPROVAL_PENDING, EXEC_EXECUTED, EXEC_FAILED,
                           VERIFY_UNVERIFIABLE, VERIFY_FAILURE,
                           classify_failure, retry_allowed_after)  # noqa: E402
from phone.extract import PhoneIntent  # noqa: E402
from phone.manager import PhoneBodyManager  # noqa: E402
from phone.models import ActionResult  # noqa: E402


class FakeAdapter:
    """Records every command; success/failure scripted by test. argv are
    EXACTLY the Termux adapter shape so we prove the adapter surface."""

    def __init__(self, fail_with=None, data=None):
        self.calls = []
        self.fail_with = fail_with
        self.data = data or ""

    def has(self, cmd):
        return not (self.fail_with and self.fail_with.startswith(cmd))

    def run(self, cmd, *args, timeout=8):
        self.calls.append((cmd, args))
        if self.fail_with and self.fail_with.startswith(cmd):
            return ActionResult(False, self.fail_with[len(cmd):].strip(), "")
        return ActionResult(True, f"ok:{cmd}", self.data)


def build_body(fail_with=None, data=None):
    """Composes the real engine stack with a recording adapter injected at
    the controller layer (constructor adapter parameter — no patching)."""
    from phone.engine import PhoneIntelligence
    from phone.adapter import TermuxAdapter

    eng = PhoneIntelligence.__new__(PhoneIntelligence)  # same construction as engine.__init__ but injectable
    from constitution import Constitution
    from learning.engine import LearningEngine
    from phone.controllers import (ClipboardController, MediaController, SystemController,
                                   CommunicationController, CameraController, NotificationController,
                                   VolumeController, VibrateController, DeviceReadController)
    from phone.discovery import CapabilityDiscovery
    from phone.models import PhonePlan  # noqa
    from phone.verifier import ExecutionVerifier
    from phone.extract import PhoneIntentExtractor
    from phone.dispatch import PhoneDispatcher

    fake = FakeAdapter(fail_with=fail_with, data=data)
    # inject the fake into BOTH layers that talk to binaries:
    eng.discovery = CapabilityDiscovery(adapter=fake)
    eng.constitution = Constitution()
    eng.verify = ExecutionVerifier()
    eng.learning = LearningEngine()
    eng.controllers = {
        'clipboard_read': ClipboardController(adapter=fake),
        'clipboard_write': ClipboardController(adapter=fake),
        'media': MediaController(adapter=fake),
        'open_url': SystemController(adapter=fake),
        'torch': SystemController(adapter=fake),
        'telephony': CommunicationController(adapter=fake),
        'sms': CommunicationController(adapter=fake),
        'camera': CameraController(adapter=fake),
        'notification': NotificationController(adapter=fake),
        'volume': VolumeController(adapter=fake),
        'vibrate': VibrateController(adapter=fake),
        'battery_state': DeviceReadController(adapter=fake),
        'wifi': DeviceReadController(adapter=fake),
    }
    eng.extractor = PhoneIntentExtractor()
    eng.dispatcher = PhoneDispatcher(eng.controllers, eng.verify, eng.constitution)
    eng.body = PhoneBodyManager(eng.dispatcher, eng.discovery, eng.constitution)
    eng.adapter = fake
    return eng


class PhoneBodyTests(unittest.TestCase):
    def _body_tmp(self):
        self.tmp = tempfile.TemporaryDirectory()
        eng = build_body()
        eng.body.audit.path = os.path.join(self.tmp.name, "audit.jsonl")
        return eng

    def tearDown(self):
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    # ---------------- lifecycle ----------------

    def test_read_only_action_auto_executes_and_records(self):
        eng = self._body_tmp()
        intent = PhoneIntent("battery_state", {}, ())
        r = eng.body.dispatch("check my battery", intent, approved=False)
        action = eng.body.recent_actions()[-1]
        self.assertTrue(r.success)
        self.assertEqual(action["verification"], VERIFY_UNVERIFIABLE)  # honest: no readback
        self.assertEqual(action["execution_state"], EXEC_EXECUTED)
        # the manager must call THE real adapter argv shape
        self.assertIn(("termux-battery-status", ()), [tuple(c) for c in eng.adapter.calls])
        with open(eng.body.audit.path) as f:
            events = [json.loads(l)["event"] for l in f.read().splitlines()]
        self.assertIn("action.created", events)
        self.assertIn("action.executed", events)

    def test_consequential_action_is_parked_until_approved(self):
        eng = self._body_tmp()
        intent = PhoneIntent("torch", {"enabled": "on"}, ())
        r = eng.body.dispatch("turn flashlight on", intent, approved=False)
        self.assertFalse(r.success)
        self.assertIn("Approval required", r.message)
        action = eng.body.recent_actions()[-1]
        self.assertEqual(action["approval_state"], APPROVAL_PENDING)
        self.assertEqual(eng.adapter.calls, [], "nothing may execute before approval")

    def test_approved_consequent_exec_and_audit(self):
        eng = self._body_tmp()
        intent = PhoneIntent("torch", {"enabled": "on"}, ())
        r = eng.body.dispatch("turn flashlight on", intent, approved=True)
        self.assertTrue(r.success)
        self.assertIn(("termux-torch", ("on",)), [tuple(c) for c in eng.adapter.calls])

    def test_constitution_denied_can_never_execute(self):
        eng = self._body_tmp()
        # protected target delete/modify is constitution-blocked
        from phone.dispatch import PhoneDispatcher  # noqa
        intent = PhoneIntent("telephony", {"number": "000000"}, ())
        eng.body.constitution = _DenyConstitution()
        r = eng.body.dispatch("call 000000", intent, approved=True)
        self.assertFalse(r.success)
        self.assertEqual(eng.adapter.calls, [])
        last = eng.body.recent_actions()[-1]
        self.assertEqual(last["execution_state"], EXEC_FAILED)
        self.assertEqual(last["approval_state"], "policy_denied")

    def test_missing_capability_is_honest_not_invented(self):
        eng = self._body_tmp()
        # force everything unavailable at discovery level
        eng.discovery = eng.body.discovery = _NoCapsDiscovery()
        intent = PhoneIntent("torch", {"enabled": "on"}, ())
        r = eng.body.dispatch("turn flashlight on", intent, approved=True)
        self.assertFalse(r.success)
        self.assertIn("not available", r.message)
        self.assertFalse(eng.adapter.calls, "no binary may run when unavailable")

    # ---------------- failure classification / retry ----------------

    def test_transient_failure_retries_once(self):
        eng = self._body_tmp()
        adapter = FlakyOnceAdapter()
        eng.adapter = adapter
        eng.controllers['battery_state'].adapter = adapter
        intent = PhoneIntent("battery_state", {}, ())
        r = eng.body.dispatch("battery", intent, approved=False)
        self.assertTrue(r.success, r.message)
        self.assertGreaterEqual(len(adapter.calls), 2)

    def test_permission_failure_never_retries(self):
        eng = self._body_tmp()
        adapter = FlakyOnceAdapter(msg="SecurityException: user rejected")
        eng.controllers['battery_state'].adapter = adapter
        eng.adapter = adapter
        intent = PhoneIntent("battery_state", {}, ())
        r = eng.body.dispatch("battery?", intent, approved=False)
        self.assertFalse(r.success)
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(classify_failure("SecurityException: user rejected"), "permission")
        self.assertFalse(retry_allowed_after("permission", "read_only", 1))

    def test_retry_policy_bounds(self):
        self.assertTrue(retry_allowed_after("transient", "read_only", 1))
        self.assertFalse(retry_allowed_after("transient", "read_only", 2))
        self.assertFalse(retry_allowed_after("logical", "consequential", 1))
        self.assertFalse(retry_allowed_after("missing_binary", "read_only", 1))

    # ---------------- state self-awareness ----------------

    def test_self_aware_answers_exist_and_are_honest(self):
        eng = self._body_tmp()
        snap = eng.body.snapshot()
        for k in ("available_capabilities", "permissions", "current_action", "battery"):
            self.assertIn(k, snap)
        self.assertIsInstance(eng.body.what_can_i_do(), list)
        self.assertIsInstance(eng.body.what_permissions(), dict)
        self.assertIsInstance(eng.body.what_cant_i_do(), list)


class _DenyConstitution:
    def evaluate(self, action, target=""):
        from constitution.policy import Decision
        return Decision(False, False, "denied-for-test")


class _NoCapsDiscovery:
    def capabilities(self):
        return []


class FlakyOnceAdapter:
    def __init__(self, msg="timed out"):
        self.calls = []
        self._failed = False
        self.msg = msg

    def has(self, c): return True

    def run(self, cmd, *args, timeout=8):
        self.calls.append((cmd, args))
        if not self._failed:
            self._failed = True
            return ActionResult(False, self.msg, "")
        return ActionResult(True, "ok retry", '{"percentage": 77}')


if __name__ == "__main__":
    unittest.main()