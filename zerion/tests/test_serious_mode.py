# tests/test_serious_mode.py
"""Serious Mode: multilingual activation, authenticated engagement, secrecy
hygiene of the credential, strictest-policy interaction with comms. Offline,
isolated DB and memory paths."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout


class Guard(unittest.TestCase):
    def setUp(self):
        import knowledge.database as kdb
        self._kdb_old = kdb.Database.__init__.__defaults__
        kdb.Database.__init__.__defaults__ = (os.path.join(tempfile.mkdtemp(), "s.db"),)
        import comms.store as cs
        cs._POPULATED = False
        import memory.memory_manager as mm
        self._mem_old = mm.MEMORY_PATH
        self._bak_old = mm.BACKUP_PATH
        mm.MEMORY_PATH = os.path.join(tempfile.mkdtemp(), "m.json")
        mm.BACKUP_PATH = mm.MEMORY_PATH + ".bak"
        from security import serious_auth
        serious_auth._attempts.update(fails=0, locked_until=0.0)
        import personality
        if personality.serious_active():
            personality.set_mode(personality.NORMAL)
        # neutralize any file-derived state from previous tests
        import config
        self._c = config
        self._levels = (config.COMM_DEFAULT_LEVEL, config.COMM_TRUSTED_RAW)
        config.COMM_DEFAULT_LEVEL = 2
        config.COMM_TRUSTED_RAW = "[]"

    def tearDown(self):
        import knowledge.database as kdb
        kdb.Database.__init__.__defaults__ = self._kdb_old
        import memory.memory_manager as mm
        mm.MEMORY_PATH = self._mem_old
        mm.BACKUP_PATH = self._bak_old
        import personality
        if personality.serious_active():
            personality.set_mode(personality.NORMAL)
        from security import serious_auth
        serious_auth._attempts.update(fails=0, locked_until=0.0)
        self._c.COMM_DEFAULT_LEVEL, self._c.COMM_TRUSTED_RAW = self._levels

    def cmd(self, text):
        from intent import commands
        return commands.handle(text, None, {})

    def activate_serious(self, code="nano 808"):
        self.cmd("turn on serious mode")
        return self.cmd(code)


class TestMultilingual(Guard):
    def test_activation_phrases(self):
        from intent.multilingual import match
        for phrase in ("Turn on serious mode", "Activate serious mode",
                       "Enable serious mode", "Switch to serious mode",
                       "SERIOUS MODE ON", "فعل الوضع الجاد", "شغل الوضع الجاد",
                       "فعل Serious Mode", "ادخل للوضع الجاد"):
            m = match(phrase)
            self.assertIsNotNone(m, phrase)
            self.assertEqual(m["intent"], "ENABLE_SERIOUS_MODE", phrase)

    def test_deactivation_phrases(self):
        from intent.multilingual import match
        for phrase in ("Turn off serious mode", "Disable serious mode",
                       "Exit serious mode", "عطل الوضع الجاد", "وقف الجاد"):
            m = match(phrase)
            self.assertIsNotNone(m, phrase)
            self.assertEqual(m["intent"], "DISABLE_SERIOUS_MODE", phrase)

    def test_flow_commands(self):
        from intent.multilingual import match
        for phrase in ("Reply to people on Instagram",
                       "Answer my Instagram messages", "Respond to Instagram DMs",
                       "رد على الناس في إنستغرام", "رد على الناس فالانستا",
                       "جاوب الناس في انستغرام", "جاوب على الميساجات في انستا"):
            m = match(phrase)
            self.assertIsNotNone(m, phrase)
            self.assertEqual(m["intent"], "START_COMM_FLOW", phrase)
            self.assertEqual(m["platform"], "instagram", phrase)

    def test_negation_never_starts_flow(self):
        from intent.multilingual import match
        self.assertIsNone(match("don't reply to people on Instagram"))
        self.assertIsNone(match("ما تردش على الناس في انستا"))

    def test_unrelated_phrases_untouched(self):
        from intent.multilingual import match
        self.assertIsNone(match("what's the weather like today"))
        self.assertIsNone(match("how serious is this bug"))  # topic-only


class TestAuthFlow(Guard):
    def test_challenge_then_success(self):
        r = self.cmd("turn on serious mode")
        self.assertIn("authentication", r.lower())
        self.assertIn("password", r.lower())
        r2 = self.cmd("nano 808")
        self.assertIn("SERIOUS MODE: ON", r2)
        import personality
        self.assertTrue(personality.serious_active())

    def test_supported_variants_all_accept(self):
        for variant in ("Nano 808", "nano808", "Nano808", "نانو 808", "نانو808"):
            import personality
            personality.set_mode(personality.NORMAL)
            r = self.cmd("turn on serious mode")
            self.assertIn("authentication", r.lower())
            r2 = self.cmd(variant)
            self.assertIn("SERIOUS MODE: ON", r2, variant)
            personality.set_mode(personality.NORMAL)

    def test_wrong_password_denied_and_counted(self):
        from security import serious_auth
        self.cmd("turn on serious mode")
        r = self.cmd("let me in please")
        self.assertIn("failed", r.lower())
        import personality
        self.assertFalse(personality.serious_active())
        self.assertGreaterEqual(serious_auth.attempts_state()["fails_since_unlock"], 1)

    def test_lockout_after_threshold(self):
        self.cmd("turn on serious mode"); self.cmd("bad 1")
        self.cmd("turn on serious mode"); self.cmd("bad 2")
        self.cmd("turn on serious mode"); self.cmd("bad 3")
        # threshold hit — new challenges refuse until lockout ends
        r = self.cmd("turn on serious mode")
        self.assertIn("locked", r.lower())
        # even the correct code is rejected while locked
        from security import serious_auth
        out = serious_auth.verify("nano 808")
        self.assertFalse(out["ok"], "lockout must hold even for correct input")
        self.assertGreater(out["locked_for"], 0)

    def test_no_secret_persistence_anywhere(self):
        # the password's IDENTITY is what must never persist — a bare "808"
        # match would false-positive on timestamps/hex ids; we assert on the
        # code's distinctive forms (word+digits), and on the wordpair together
        import memory.memory_manager as mm
        from knowledge.manager import KnowledgeManager
        self.cmd("turn on serious mode")
        self.cmd("Nano 808")
        distinctive = ("nano 808", "nano808", "نانو 808", "نانو808", "Nano 808")
        memory_blob = json.dumps(mm.load_memory())
        for form in distinctive:
            self.assertNotIn(form, memory_blob, "memory must never carry the code")
        rows = KnowledgeManager().db.query("SELECT content FROM records")
        blob = "\n".join(r["content"] for r in rows)
        for form in distinctive:
            self.assertNotIn(form, blob)
        # and no record may hold BOTH word and digits separately
        body = blob.lower()
        self.assertFalse("nano" in body and "808" in body,
                         "even split-form persistence is a leak")
        from comms import audit
        journal = json.dumps(audit.tail(50))
        for form in distinctive:
            self.assertNotIn(form, journal)

    def test_no_secret_in_stdout_or_pending_state(self):
        buf = io.StringIO()
        from intent import commands
        with redirect_stdout(buf):
            commands.handle("turn on serious mode", None, {})
            self.assertTrue(commands.pending_secret_input())
            commands.handle("nano808", None, {})
            self.assertFalse(commands.pending_secret_input())
        out = buf.getvalue()
        self.assertNotIn("808", out)
        self.assertNotIn("nano", out.lower())

    def test_auth_file_contains_only_kdf_artifacts(self):
        from security import serious_auth
        serious_auth._ensure_secret()
        with open(serious_auth._path(), encoding="utf-8") as f:
            blob = json.load(f)
        self.assertEqual(blob["algo"], "pbkdf2-sha256")
        self.assertNotIn("nano", json.dumps(blob).lower())
        self.assertNotIn("808", json.dumps(blob))

    def test_serious_never_bypasses_constitution(self):
        # serious mode on: destructive tools STILL require confirmation
        self.activate_serious()
        from tools.manager import tool_manager
        result = tool_manager.execute("run_shell", {"command": "echo hi"})
        self.assertEqual(result.error, "confirmation_required",
                         "serious mode must NOT bypass the confirmation flow")
        tool_manager.cancel_pending_confirmation()
        from constitution.constitution import ConstitutionEngine
        self.assertTrue(ConstitutionEngine.verify_lock())


class TestSeriousPolicyInteraction(Guard):
    def _wire(self):
        from comms import conversation_state, quality, bgworkflows
        conversation_state.touch("telegram", "bot", "777", sender="amina", topic="ops")
        quality.set_shadow("telegram", "graduated")
        bgworkflows.start("telegram", account="bot", ttl_s=3600)
        self._c.COMM_DEFAULT_LEVEL = 3
        self._c.COMM_TRUSTED_RAW = '[{"platform":"telegram","recipient":"777"}]'

    def test_serious_demotes_auto_to_confirm(self):
        self._wire()
        from comms.decision import evaluate
        from comms.models import Draft, UnifiedMessage
        msg = UnifiedMessage(platform="telegram", account="bot", sender="amina",
                             content="are we good?", conversation_id="777")
        cand = Draft(platform="telegram", recipient="777", body="yes, green")
        import personality
        personality.set_mode(personality.NORMAL)
        d1 = evaluate(msg, cand, "authenticated", {}, critic_verdict="accept")
        self.assertEqual(d1.mode, "autonomous")
        personality.set_mode(personality.SERIOUS)
        d2 = evaluate(msg, cand, "authenticated", {}, critic_verdict="accept")
        self.assertEqual(d2.mode, "approval")
        self.assertTrue(any(r.startswith("serious_mode_strictest_policy")
                            for r in d2.reasons))

    def test_serious_ui_settings_payload(self):
        from ui.server import _current_settings
        import personality
        personality.set_mode(personality.NORMAL)
        self.assertFalse(_current_settings()["serious_mode"])
        personality.set_mode(personality.SERIOUS)
        self.assertTrue(_current_settings()["serious_mode"])


if __name__ == "__main__":
    unittest.main()
