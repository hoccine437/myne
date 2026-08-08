# tests/test_communication_layer.py
"""Communication & Action Layer — full runtime verification.

Everything here is OFFLINE HERMETIC: knowledge/comm tables are redirected to
a scratch SQLite file per test class, and connectors with live transports are
exercised ONLY through injected fakes. Live IMAP/SMTP/Telegram delivery is
explicitly NOT VERIFIED from tests (it needs real authorized accounts) — what
is proven is the complete pipeline behavior end to end.
"""

import json
import os
import tempfile
import time
import unittest


def _isolate():
    """Bind every Database() constructed while active to a scratch file.
    (Database.__init__ binds path=DB_PATH at definition time — the same
    __defaults__ technique test_cognition_influence uses.)"""
    import knowledge.database as kdb
    old_defaults = kdb.Database.__init__.__defaults__
    scratch = os.path.join(tempfile.mkdtemp(), "c.db")
    kdb.Database.__init__.__defaults__ = (scratch,)
    import comms.store as cs
    cs._POPULATED = False

    def restore():
        kdb.Database.__init__.__defaults__ = old_defaults
    return restore


class ConfigGuard(unittest.TestCase):
    """Keep comm config hermetic: COMM_ENABLED/levels/trusted restored after."""

    def setUp(self):
        self._restore_db = _isolate()
        import config
        self._c = config
        self._saved = {k: getattr(config, k) for k in (
            "COMM_ENABLED", "COMM_DEFAULT_LEVEL", "COMM_TRUSTED_RAW",
            "EMAIL_HOST", "EMAIL_USER", "EMAIL_PASSWORD",
            "TELEGRAM_BOT_TOKEN", "GEMINI_API_KEY",
            "COMM_RATE_PER_MINUTE", "COMM_MAX_RECIPIENTS",
            "COMM_DUPLICATE_WINDOW", "COMM_RECIPIENT_COOLDOWN")}
        config.COMM_ENABLED = True
        config.COMM_DEFAULT_LEVEL = 2
        config.COMM_TRUSTED_RAW = "[]"
        config.EMAIL_HOST = ""
        config.EMAIL_USER = ""
        config.EMAIL_PASSWORD = ""
        config.TELEGRAM_BOT_TOKEN = ""
        config.GEMINI_API_KEY = ""

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(self._c, k, v)
        self._restore_db()


# ---------------------------------------------------------------------------
# normalization + classification
# ---------------------------------------------------------------------------

class TestModels(ConfigGuard):
    def test_unified_message_contract(self):
        from comms.models import UnifiedMessage
        m = UnifiedMessage(platform="email", sender="a@b.io", content="hello",
                           conversation_id="c1", account="me@b.io")
        d = m.to_dict()
        for key in ("message_id", "platform", "account", "sender", "recipients",
                    "timestamp", "content", "attachments", "conversation_id",
                    "reply_context", "permissions", "status"):
            self.assertIn(key, d)

    def test_stable_dedup(self):
        """Redelivery shares the platform timestamp; a same-content message a
        minute later is a DIFFERENT message, not a duplicate."""
        from comms.models import UnifiedMessage
        from comms.inbox import ingest
        m = UnifiedMessage(platform="telegram", sender="a", content="same body",
                           conversation_id="c", timestamp=1730000000.0)
        first = ingest(m)
        again = ingest(UnifiedMessage(platform="telegram", sender="a",
                                      content="same body", conversation_id="c",
                                      timestamp=1730000000.0))  # redelivered copy
        self.assertTrue(first["stored"])
        self.assertTrue(again["duplicate"])

    def test_classification_categories(self):
        from comms.classify import classify_message
        from comms.models import UnifiedMessage
        cases = [
            ("URGENT: server down, action required", "urgent"),
            ("your invoice #42 is attached", "financial"),
            ("can we meet about the sprint review?", "work"),
            ("unsubscribe from our lottery newsletter, winner!", "spam"),
            ("security alert: new sign-in detected", "system"),
        ]
        for body, want in cases:
            m = classify_message(UnifiedMessage(platform="email", sender="x",
                                                content=body))
            self.assertEqual(m.classification, want, body)

    def test_risk_markers_no_false_substring(self):
        from comms.classify import risk_markers
        # 'nda' must not fire inside 'calendar'; short markers need boundaries
        self.assertEqual(risk_markers("put it in the calendar for me"), ())
        self.assertIn("legal", risk_markers("please review this NDA before signing"))
        self.assertIn("credentials", risk_markers("what's the wifi password?"))


# ---------------------------------------------------------------------------
# inbox views
# ---------------------------------------------------------------------------

class TestInbox(ConfigGuard):
    def test_views(self):
        from comms.inbox import ingest, prioritized, group_by_person, group_by_task, search, summarize
        from comms.models import UnifiedMessage
        ingest(UnifiedMessage(platform="email", sender="boss@corp.io",
                              content="URGENT: please send the deploy report today", timestamp=1.0))
        ingest(UnifiedMessage(platform="telegram", sender="amina",
                              content="lunch next week?", timestamp=2.0))
        self.assertIn("boss@corp.io", group_by_person())
        self.assertTrue(group_by_task()["has_task"])
        self.assertEqual(prioritized()[0]["sender"], "boss@corp.io")  # urgent first
        self.assertTrue(search("lunch"))
        self.assertIn("2 message(s)", summarize())


# ---------------------------------------------------------------------------
# connectors
# ---------------------------------------------------------------------------

class _FakeIMAP:
    def __init__(self, host, port): pass
    def login(self, u, p):
        assert u and p
    def select(self, box): pass
    def search(self, enc, scope): return "OK", [b"1 2 3"]
    def fetch(self, mid, spec):
        hdr = (b"From: Karim <karim@friend.io>\r\nSubject: Climbing Saturday?\r\n"
               b"Message-ID: <m42>\r\n\r\n")
        return "OK", [(b"1", hdr)]
    def logout(self): pass


class _FakeSMTP:
    sent = []
    def __init__(self, host, port, timeout=20): pass
    def login(self, u, p): assert p
    def sendmail(self, frm, to, msg):
        _FakeSMTP.sent.append((frm, to, msg)); return {}
    def quit(self): pass


class TestEmailConnector(ConfigGuard):
    def setUp(self):
        super().setUp()
        self._c.EMAIL_HOST = "imap.test.invalid"
        self._c.EMAIL_USER = "me@test.invalid"
        self._c.EMAIL_PASSWORD = "test-only-secret"
        from comms.connectors.email_connector import EmailConnector
        self.conn = EmailConnector(imap_cls=_FakeIMAP, smtp_cls=_FakeSMTP)

    def test_read_normalizes(self):
        msgs = self.conn.read(limit=5)
        self.assertEqual(len(msgs), 3)
        self.assertEqual(msgs[0].platform, "email")
        self.assertIn("karim", msgs[0].sender.lower())
        self.assertEqual(msgs[0].reply_context, "Climbing Saturday?")
        self.assertIn("can_read", msgs[0].permissions)

    def test_send_records_mail(self):
        from comms.models import Draft
        _FakeSMTP.sent.clear()
        d = Draft(platform="email", recipient="karim@friend.io", body="see you at 10")
        res = self.conn.send(d)
        self.assertTrue(res["ok"])
        self.assertEqual(len(_FakeSMTP.sent), 1)
        self.assertIn(b"see you at 10", _FakeSMTP.sent[0][2])

    def test_unconfigured_connector_is_honest(self):
        from comms.connectors.email_connector import EmailConnector
        self._c.EMAIL_PASSWORD = ""
        bare = EmailConnector()
        self.assertFalse(bare.configured())
        self.assertEqual(bare.health()["state"], "disconnected")
        self.assertEqual(bare.read(), [])
        res = bare.send(object())
        self.assertFalse(res["ok"])

    def test_never_exposes_secret(self):
        self.assertNotIn("test-only-secret", json.dumps(self.conn.health()))


class TestTelegramConnector(ConfigGuard):
    def setUp(self):
        super().setUp()
        self._c.TELEGRAM_BOT_TOKEN = "123:test-token"
        self.sent = []

        def fake_http(url, data):
            if "getMe" in url:
                return {"ok": True, "result": {"username": "zerion_test_bot"}}
            if "getUpdates" in url:
                return {"ok": True, "result": [{"update_id": 9, "message": {
                    "message_id": 5, "date": int(time.time()),
                    "text": "please check the lights",
                    "chat": {"id": 777, "title": "Home"},
                    "from": {"username": "sam"}}}]}
            if "sendMessage" in url:
                self.sent.append(data)
                return {"ok": True, "result": {"message_id": 314}}
            return {"ok": False}

        from comms.connectors.telegram import TelegramConnector
        self.conn = TelegramConnector(http=fake_http)

    def test_health_authenticated(self):
        h = self.conn.health()
        self.assertEqual(h["state"], "authenticated")
        self.assertIn("zerion_test_bot", h["detail"])
        self.assertNotIn("123:test-token", json.dumps(h))

    def test_poll_normalizes(self):
        events = self.conn.poll_events()
        self.assertEqual(len(events), 1)
        m = events[0]
        self.assertEqual(m.platform, "telegram")
        self.assertEqual(m.sender, "sam")
        self.assertEqual(m.conversation_id, "777")
        self.assertIn("lights", m.content)

    def test_send_verify_shape(self):
        from comms.models import Draft
        res = self.conn.send(Draft(platform="telegram", recipient="777",
                                   body="lights are fine"))
        self.assertTrue(res["ok"], res)
        self.assertIn("314", res["platform_result"])
        self.assertEqual(self.sent[0]["chat_id"], "777")

    def test_send_rejects_wrong_platform(self):
        from comms.models import Draft
        res = self.conn.send(Draft(platform="email", recipient="x@y.io", body="nope"))
        self.assertFalse(res["ok"])

    def test_unconfigured_disconnected(self):
        self._c.TELEGRAM_BOT_TOKEN = ""
        from comms.connectors.telegram import TelegramConnector
        bare = TelegramConnector(http=lambda u, d: {"ok": True})
        self.assertFalse(bare.configured())
        self.assertEqual(bare.health()["state"], "disconnected")


class TestPhoneInboxConnector(ConfigGuard):
    def test_honest_without_termux(self):
        from comms.connectors.phone_inbox import PhoneInboxConnector
        from phone.adapter import TermuxAdapter
        conn = PhoneInboxConnector(adapter=TermuxAdapter())
        # sandbox has no termux-notification-list → must report disconnected
        self.assertEqual(conn.health()["state"], "disconnected")
        self.assertEqual(conn.read(), [])

    def test_normalizes_social_notifications(self):
        from comms.connectors.phone_inbox import PhoneInboxConnector
        from phone.models import ActionResult

        class FakeAdapter:
            def has(self, cmd): return True
            def run(self, cmd, *a, timeout=8):
                return ActionResult(True, "", json.dumps([{
                    "packageName": "com.whatsapp", "title": "Yasmine",
                    "content": "shall we talk at 6?", "id": 12,
                    "when": 1730000000000}]))

        conn = PhoneInboxConnector(adapter=FakeAdapter())
        msgs = conn.read()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].platform, "social")
        self.assertEqual(msgs[0].account, "whatsapp")
        self.assertIn("talk at 6", msgs[0].content)
        self.assertEqual(conn.health()["state"], "connected")

    def test_send_refused_honestly(self):
        from comms.connectors.phone_inbox import PhoneInboxConnector
        conn = PhoneInboxConnector()
        res = conn.send(object())
        self.assertFalse(res["ok"])
        self.assertIn("supervised", res["platform_result"])


# ---------------------------------------------------------------------------
# approvals / rails / audit / verify
# ---------------------------------------------------------------------------

class TestApprovalLadder(ConfigGuard):
    def test_levels(self):
        from comms import approvals
        self.assertEqual(approvals.decide("email", "", "a@b.io", "hello").action,
                         "confirm")  # default level 2
        approvals.set_level("email", 0)
        self.assertEqual(approvals.decide("email", "", "a@b.io", "hello").action,
                         "observe")
        approvals.revoke("email")
        # back to default after revoke
        self.assertEqual(approvals.decide("email", "", "a@b.io", "hello").action,
                         "confirm")
        approvals.set_level("email", 3)
        self._c.COMM_TRUSTED_RAW = '[{"platform":"email","recipient":"a@b.io"}]'
        self.assertEqual(approvals.decide("email", "", "a@b.io", "standup notes sent").action,
                         "auto")

    def test_high_risk_forces_confirm_even_when_trusted(self):
        from comms import approvals
        approvals.set_level("email", 3)
        self._c.COMM_TRUSTED_RAW = '[{"platform":"email","recipient":"a@b.io"}]'
        d = approvals.decide("email", "", "a@b.io", "please wire the payment today")
        self.assertEqual(d.action, "confirm")
        self.assertIn("financial", d.risk)

    def test_mass_send_denied(self):
        from comms import approvals
        d = approvals.decide("email", "", "x@y.io", "blast", recipient_count=99)
        self.assertEqual(d.action, "deny")

    def test_comm_disabled_denies(self):
        from comms import approvals
        self._c.COMM_ENABLED = False
        self.assertEqual(approvals.decide("email", "", "a@b.io", "hi").action, "deny")


class TestAntiSpamRails(ConfigGuard):
    def test_duplicate_and_cooldown(self):
        from comms import ratelimit
        self.assertTrue(ratelimit.check("local", "bob", "hello").allowed)
        ratelimit.record("local", "bob", "hello")
        self.assertFalse(ratelimit.check("local", "bob", "hello").allowed)   # duplicate
        self.assertFalse(ratelimit.check("local", "bob", "other").allowed)   # cooldown

    def test_platform_rate_cap(self):
        from comms import ratelimit
        self._c.COMM_RECIPIENT_COOLDOWN = 0
        self._c.COMM_RATE_PER_MINUTE = 3
        for i in range(3):
            self.assertTrue(ratelimit.check("local", f"r{i}", f"m{i}").allowed)
            ratelimit.record("local", f"r{i}", f"m{i}")
        self.assertFalse(ratelimit.check("local", "r9", "m9").allowed)

    def test_mass_recipients(self):
        from comms import ratelimit
        self.assertFalse(ratelimit.check("local", "g", "x",
                                         recipient_count=99).allowed)


class TestVerify(ConfigGuard):
    def test_recipient_shapes(self):
        from comms.verify import _recipient_ok
        self.assertTrue(_recipient_ok("email", "a@b.io"))
        self.assertFalse(_recipient_ok("email", "not-an-email"))
        self.assertTrue(_recipient_ok("phone", "+2135550100"))
        self.assertTrue(_recipient_ok("telegram", "777"))

    def test_content_and_attachment_checks(self):
        from comms.models import Draft
        from comms.verify import pre_send_checklist
        d = Draft(platform="email", recipient="a@b.io", body="",
                  attachments=({"name": "gone.txt", "local_path": "/no/such/file"},))
        checks = pre_send_checklist(d)
        self.assertFalse(checks["content_ok"])
        self.assertFalse(checks["attachments_ok"])


# ---------------------------------------------------------------------------
# the send pipeline (policy → checks → rails → connector → verify → audit)
# ---------------------------------------------------------------------------

class TestSendPipeline(ConfigGuard):
    def _wired(self):
        from comms.registry import connectors
        from comms.connectors.telegram import TelegramConnector
        self._c.TELEGRAM_BOT_TOKEN = "123:test-token"   # present, never asserted-against
        self.sent = []

        def fake_http(url, data):
            if "getMe" in url:
                return {"ok": True, "result": {"username": "bot"}}
            if "sendMessage" in url:
                self.sent.append(data)
                return {"ok": True, "result": {"message_id": 77}}
            return {"ok": True, "result": []}

        conn = TelegramConnector(http=fake_http)
        connectors.inject(conn)
        return conn

    def tearDown(self):
        from comms.registry import connectors
        connectors.eject("telegram")
        super().tearDown()

    def test_confirm_flow_blocks_unconfirmed(self):
        from comms.models import Draft
        from comms.engine import send_draft
        from comms import store
        self._wired()
        d = Draft(platform="telegram", recipient="777", body="hi there")
        store.store_draft(d)
        out = send_draft(d, confirmed=False)
        self.assertEqual(out["status"], "needs_approval")
        self.assertEqual(self.sent, [])

    def test_confirmed_send_verifies_and_audits(self):
        from comms.models import Draft
        from comms.engine import send_draft
        from comms import store, audit
        from learning.errors import ErrorMemory
        self._wired()
        d = Draft(platform="telegram", recipient="777", body="the report is attached")
        store.store_draft(d)
        out = send_draft(d, confirmed=True, workflow="wf-test", agent="communicator")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["verification"], "message_id 77")
        self.assertEqual(len(self.sent), 1)
        row = store.get_draft(d.draft_id)
        self.assertEqual(row["status"], "sent")
        entries = audit.tail(5)
        last = entries[-1]
        self.assertEqual(last["action"], "send")
        self.assertEqual(last["platform"], "telegram")
        self.assertEqual(last["workflow"], "wf-test")
        self.assertEqual(last["agent"], "communicator")
        self.assertEqual(last["verification"], "message_id 77")
        self.assertNotIn("test-token", json.dumps(entries))

    def test_failed_send_goes_to_error_memory(self):
        from comms.models import Draft
        from comms.engine import send_draft
        from comms.registry import connectors
        from comms.connectors.telegram import TelegramConnector
        from learning.errors import ErrorMemory

        self._c.TELEGRAM_BOT_TOKEN = "123:test-token"

        def refusing_http(url, data):
            if "sendMessage" in url:
                return {"ok": False, "description": "chat not found"}
            return {"ok": True, "result": {"username": "bot"}}

        connectors.inject(TelegramConnector(http=refusing_http))
        d = Draft(platform="telegram", recipient="999", body="status update")
        out = send_draft(d, confirmed=True)
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], "failed")
        self.assertIn("chat not found", out["platform_result"])
        similar = ErrorMemory().retrieve_similar("send telegram message to 999", 5)
        self.assertTrue(similar, "failed sends must land in error memory")

    def test_risky_send_needs_confirmation_by_policy(self):
        from comms import approvals
        from comms.models import Draft
        from comms.engine import send_draft
        self._wired()
        approvals.set_level("telegram", 3)
        self._c.COMM_TRUSTED_RAW = '[{"platform":"telegram","recipient":"777"}]'
        d = Draft(platform="telegram", recipient="777",
                  body="please process the payment invoice today")
        out = send_draft(d, confirmed=False)
        self.assertEqual(out["status"], "needs_approval")   # risk forces confirm
        self.assertEqual(self.sent, [])


# ---------------------------------------------------------------------------
# contacts + calendar + reply engine
# ---------------------------------------------------------------------------

class TestContacts(ConfigGuard):
    def test_lookup_and_context(self):
        from comms import store
        from comms.contacts import lookup, context_for
        store.upsert_contact("Amina K", identifier="amina@corp.io",
                             platform="email", notes="colleague")
        got = lookup("amina@corp.io")
        self.assertEqual(got["name"], "Amina K")
        self.assertIn("email", got["platforms"])
        store.contact_note("Amina K", "sprint review planning")
        self.assertEqual(context_for("amina@corp.io")["last_topic"],
                         "sprint review planning")
        self.assertIsNone(lookup("nobody-xyz@nowhere.io"))

    def test_inbox_sync_is_minimal(self):
        from comms.inbox import ingest
        from comms.contacts import sync_from_inbox, lookup
        from comms.models import UnifiedMessage
        ingest(UnifiedMessage(platform="telegram", sender="karim_io",
                              content="hello", timestamp=5.0))
        n = sync_from_inbox()
        self.assertGreaterEqual(n, 1)
        contact = lookup("karim_io")
        self.assertIsNotNone(contact)
        self.assertFalse(contact.get("notes"), "no content profiling")


class TestCalendar(ConfigGuard):
    def test_create_conflict_cancel(self):
        from comms import calendar
        base = time.time() + 3600
        first = calendar.create("Dentist", base, 60)
        self.assertTrue(first["ok"])
        clash = calendar.create("Call with boss", base + 1800, 30)
        self.assertEqual(clash["conflicts"], ["Dentist"])
        self.assertTrue(calendar.upcoming(2))
        # cancel BOTH originals; the slot must then be completely free
        self.assertTrue(calendar.cancel(first["event_id"])["ok"])
        self.assertTrue(calendar.cancel(clash["event_id"])["ok"])
        after = calendar.create("Call with boss", base + 1800, 30)
        self.assertEqual(after["conflicts"], [])  # cancelled events don't block

    def test_availability_math(self):
        from comms import calendar
        day_start = (time.time() // 86400) * 86400 + 86400  # tomorrow
        calendar.create("Morning Block", day_start + 9 * 3600, 120)
        free = calendar.find_availability(day_start, 60)
        self.assertTrue(free)
        self.assertFalse(any(f["start"] < day_start + 11 * 3600 and
                             f["end"] > day_start + 9 * 3600 for f in free))

    def test_suggest_time(self):
        from comms import calendar
        out = calendar.suggest_time_for("can we meet tomorrow at 5", 60)
        self.assertIn("free_slots", out)
        self.assertTrue(out["free_slots"])


class TestReplyEngine(ConfigGuard):
    def test_offline_draft_is_honest_and_contextual(self):
        from comms.inbox import ingest
        from comms.models import UnifiedMessage
        from comms.reply import draft_reply
        msg = UnifiedMessage(platform="email", account="me@x.io",
                             sender="boss@corp.io", reply_context="Q3 report",
                             content="Please send the report by tomorrow.",
                             conversation_id="t-9")
        ingest(msg)
        draft = draft_reply(msg)
        self.assertTrue(draft.generated_locally)          # no provider key in tests
        self.assertIn("[draft-local]", draft.body)          # honestly marked
        self.assertEqual(draft.recipient, "boss@corp.io")
        self.assertEqual(draft.conversation_id, "t-9")

    def test_spam_never_gets_friendly_draft(self):
        from comms.models import UnifiedMessage
        from comms.reply import draft_reply
        msg = UnifiedMessage(platform="email", sender="promo@junk.io",
                             content="You are a winner! claim now, unsubscribe")
        draft = draft_reply(msg)
        self.assertEqual(msg.classification, "spam")
        # the offline template is transactional, not chatty
        self.assertNotIn("congratulations", draft.body.lower())


# ---------------------------------------------------------------------------
# workflows
# ---------------------------------------------------------------------------

class TestWorkflows(ConfigGuard):
    def test_trigger_condition_action_learn(self):
        from comms.workflow import engine
        definition = {
            "name": "urgent-email-notify",
            "trigger": {"type": "email.new",
                        "match": {"urgency": {"op": "eq", "value": "urgent"}}},
            "steps": [
                {"action": "classify"},
                {"action": "store_inbox"},
                {"action": "store_memory", "params": {"content": "urgent mail seen",
                                                      "tag": "wf"}},
            ]}
        from comms.models import UnifiedMessage
        msg = UnifiedMessage(platform="email", sender="cto@corp.io",
                             content="URGENT: board moved up", timestamp=6.0)
        res = engine.run(definition, {"type": "email.new", "message": msg,
                                      "summary": "urgent email from cto"})
        self.assertTrue(res["success"], res)
        self.assertEqual(len(res["steps"]), 3)
        # workflow pattern stored (learning)
        from knowledge.manager import KnowledgeManager
        ctx = KnowledgeManager().retrieve_context("urgent-email-notify", 5)
        self.assertIn("workflow pattern", ctx)
        # the message was really ingested
        from comms.inbox import search
        self.assertTrue(search("board moved up"))

    def test_condition_gates_skip_politely(self):
        from comms.workflow import engine, eval_condition
        definition = {"name": "only-urgent",
                      "steps": [{"action": "store_memory",
                                 "params": {"content": "never"},
                                 "when": [{"field": "event.urgency",
                                           "op": "eq", "value": "urgent"}]}]}
        res = engine.run(definition, {"type": "event", "urgency": "low",
                                      "summary": "low prio"})
        self.assertTrue(res["success"])
        self.assertEqual(res["steps"][0]["outcome"], "skipped-condition")

    def test_failure_falls_back_and_is_recorded(self):
        from comms.workflow import engine
        from learning.errors import ErrorMemory
        definition = {"name": "boom-wf",
                      "steps": [
                          {"action": "no_such_action"},
                          {"action": "store_memory",
                           "params": {"content": "should not run"}}]}
        res = engine.run(definition, {"type": "event", "summary": "boom"})
        self.assertFalse(res["success"])
        self.assertIn("step 0", res["error"])
        similar = ErrorMemory().retrieve_similar("workflow boom-wf", 5)
        self.assertTrue(similar, "failed workflows must enter error memory")

    def test_on_fail_alternative(self):
        from comms.workflow import engine
        from comms import store
        definition = {"name": "with-fallback",
                      "steps": [
                          {"action": "no_such_action",
                           "on_fail": {"action": "store_memory",
                                       "params": {"content": "fallback ran", "tag": "wf"}}},
                          {"action": "log", "params": {"text": "done"}}]}
        res = engine.run(definition, {"type": "event", "summary": "x"})
        self.assertTrue(res["success"], res)
        names = [s["name"] for s in res["steps"]]
        self.assertIn("step0:no_such_action.on_fail", names)

    def test_workflow_recorded_runs(self):
        from comms.workflow import engine
        from comms import store
        store.save_workflow("wf-t", "testwf", {"trigger": {"type": "command"},
                                               "steps": [{"action": "log",
                                                          "params": {"text": "ok"}}]})
        engine.run({"id": "wf-t", "name": "testwf",
                    "steps": [{"action": "log", "params": {"text": "ok"}}]},
                   {"type": "command", "summary": "manual"}, workflow_id="wf-t")
        runs = store.recent_runs("wf-t")
        self.assertTrue(runs)
        self.assertEqual(runs[0]["success"], 1)


# ---------------------------------------------------------------------------
# tools + agent whitelist
# ---------------------------------------------------------------------------

class TestCommTools(ConfigGuard):
    def test_tools_registered_and_safe(self):
        from tools.manager import tool_manager
        names = {t["name"]: t for t in tool_manager.list_tools()}
        for name in ("comm_inbox", "comm_draft", "comm_send", "comm_health",
                     "contact_lookup", "calendar_list", "calendar_add",
                     "workflow_list", "workflow_run"):
            self.assertIn(name, names)
        self.assertTrue(names["comm_send"]["destructive"])
        self.assertTrue(names["calendar_add"]["destructive"])
        self.assertFalse(names["comm_inbox"]["destructive"])

    def test_destructive_flow_requires_confirmation(self):
        from tools.manager import tool_manager
        result = tool_manager.execute("calendar_add",
                                      {"title": "test-event-xyz",
                                       "start_ts": str(time.time() + 7200)})
        self.assertEqual(result.error, "confirmation_required")
        tool_manager.cancel_pending_confirmation()
        from comms import calendar
        self.assertFalse(any(e["title"] == "test-event-xyz"
                             for e in calendar.upcoming(2)),
                         "cancelled confirmation must not create the event")

    def test_communicator_agent_whitelist(self):
        from agents.types import get_type
        t = get_type("communicator")
        self.assertIsNotNone(t)
        self.assertNotIn("comm_send", t.allowed_tools,
                         "agents draft; only humans approve sends")
        self.assertTrue(t.can_search_memory)

    def test_tool_draft_and_send_roundtrip_without_connector(self):
        from comms.inbox import ingest
        from comms.models import UnifiedMessage
        from tools.manager import tool_manager
        msg = UnifiedMessage(platform="email", sender="peer@corp.io",
                             content="status?", conversation_id="cv-1",
                             timestamp=7.0)
        ing = ingest(msg)
        r1 = tool_manager.execute("comm_draft", {"stable_id": ing["stable_id"]})
        self.assertTrue(r1.success, r1.message)
        import re
        m = re.search(r"Draft (\w+)", r1.message)
        self.assertTrue(m)
        # send is destructive: first attempt parks at confirmation
        r2 = tool_manager.execute("comm_send", {"draft_id": m.group(1)})
        self.assertEqual(r2.error, "confirmation_required")
        # confirm → engine runs, fails honestly without an email connector
        r3 = tool_manager.confirm_pending()
        self.assertFalse(r3.success)
        # no email connector in tests → platform check fails honestly
        self.assertIn("platform_ok", r3.message)


# ---------------------------------------------------------------------------
# UI endpoints + scheduler
# ---------------------------------------------------------------------------

class TestCommUIEndpoints(ConfigGuard):
    def test_routes_real(self):
        from ui.server import app
        from starlette.testclient import TestClient
        client = TestClient(app)
        ov = client.get("/api/comm/overview")
        self.assertEqual(ov.status_code, 200)
        body = ov.json()
        self.assertIn("connectors", body)
        self.assertIn("inbox", body)
        self.assertEqual(client.get("/api/comm/inbox").status_code, 200)
        self.assertEqual(client.get("/api/comm/drafts").status_code, 200)
        self.assertEqual(client.get("/api/comm/workflows").status_code, 200)
        self.assertEqual(client.get("/api/comm/audit").status_code, 200)
        # 404 honesty for unknown draft
        self.assertEqual(client.post("/api/comm/send",
                                     json={"draft_id": "nope",
                                           "confirmed": True}).status_code, 404)

    def test_scheduler_idle_without_connectors(self):
        from comms.scheduler import poll_once
        self._c.EMAIL_PASSWORD = ""   # nothing configured
        from comms.registry import connectors
        connectors.invalidate()
        out = poll_once()
        self.assertEqual(out["polled"], 0)
        self.assertIn("workflows", out)
        self.assertEqual(out["ingested"], 0)

    def test_scheduler_ingests_and_fires(self):
        from comms.registry import connectors
        from comms.connectors.telegram import TelegramConnector
        from comms import store
        config_sets = self._c
        config_sets.TELEGRAM_BOT_TOKEN = "123:test-token"

        def fake_http(url, data):
            if "getUpdates" in url:
                return {"ok": True, "result": [{"update_id": 1, "message": {
                    "message_id": 2, "date": int(time.time()),
                    "text": "wake me for the demo",
                    "chat": {"id": 55}, "from": {"username": "ops"}}}]}
            if "sendMessage" in url:
                return {"ok": True, "result": {"message_id": 3}}
            return {"ok": True, "result": {"username": "b"}}

        connectors.invalidate()
        connectors.inject(TelegramConnector(http=fake_http))
        store.save_workflow("wf-demo", "demo-flow",
                            {"trigger": {"type": "telegram.new",
                                         "match": {"sender": {"op": "contains", "value": "ops"}}},
                             "steps": [{"action": "store_inbox"},
                                       {"action": "notify_user"}]})
        from comms.scheduler import poll_once
        out = poll_once()
        self.assertGreaterEqual(out["ingested"], 1)
        self.assertGreaterEqual(out["workflows"], 1)
        runs = store.recent_runs("wf-demo")
        self.assertTrue(runs)
        connectors.eject("telegram")


if __name__ == "__main__":
    unittest.main()


# ===========================================================================
# mission §36 — END-TO-END CHAINS
# ===========================================================================

class TestEndToEndChains(ConfigGuard):
    """Each chain: platform event → understand → draft → approve → send →
    verify. Transports are injected fakes; live third-party delivery remains
    NOT VERIFIED without authorized accounts and is never claimed here."""

    def _bind_telegram(self, inbox_text="can you review the deploy?"):
        from comms.registry import connectors
        from comms.connectors.telegram import TelegramConnector
        self._c.TELEGRAM_BOT_TOKEN = "123:e2e-token"
        self._tg_sent = []
        state = {"delivered": bool(inbox_text)}

        def http(url, data):
            if "getUpdates" in url:
                if not state["delivered"]:
                    return {"ok": True, "result": []}
                state["delivered"] = False
                return {"ok": True, "result": [{"update_id": 11, "message": {
                    "message_id": 21, "date": int(time.time()), "text": inbox_text,
                    "chat": {"id": 4242, "title": "Ops"}, "from": {"username": "amina"}}}]}
            if "sendMessage" in url:
                self._tg_sent.append(data)
                return {"ok": True, "result": {"message_id": 900}}
            return {"ok": True, "result": {"username": "e2e_bot"}}

        conn = TelegramConnector(http=http)
        connectors.invalidate()
        connectors.inject(conn)
        return conn

    def tearDown(self):
        from comms.registry import connectors
        connectors.eject("telegram")
        super().tearDown()

    # ---- EMAIL: receive → understand → draft → approve → send → verify ----
    def test_e2e_email(self):
        from comms.connectors.email_connector import EmailConnector
        from comms.registry import connectors
        from comms.inbox import ingest, prioritized
        from comms.reply import draft_reply
        from comms.engine import send_draft
        from comms import store, audit

        class FakeSMTP:
            sent = []
            def __init__(self, host, port, timeout=20): pass
            def login(self, u, p): pass
            def sendmail(self, frm, to, msg): FakeSMTP.sent.append(msg); return {}
            def quit(self): pass

        self._c.EMAIL_HOST = "smtp.test.invalid"
        self._c.EMAIL_USER = "me@test.invalid"
        self._c.EMAIL_PASSWORD = "e2e-secret"
        connectors.inject(EmailConnector(imap_cls=_FakeIMAP, smtp_cls=FakeSMTP))

        # receive + understand
        msgs = connectors.get("email").read(limit=5)
        self.assertTrue(msgs)
        outcome = ingest(msgs[0])
        self.assertTrue(outcome["stored"])
        rows = prioritized(platform="email")
        self.assertEqual(rows[0]["reply_context"], "Climbing Saturday?")

        # draft (+ approve path)
        reply_draft = draft_reply(msgs[0])
        self.assertTrue(reply_draft.generated_locally)  # no provider in tests
        reply_draft.checks = {}
        store.store_draft(reply_draft)
        # level 2 default → unconfirmed send parks
        parked = send_draft(reply_draft, confirmed=False)
        self.assertEqual(parked["status"], "needs_approval")
        self.assertEqual(FakeSMTP.sent, [])
        # approve → send → verify
        out = send_draft(reply_draft, confirmed=True)
        self.assertTrue(out["ok"], out)
        self.assertIn("smtp accepted", out["verification"])
        self.assertTrue(FakeSMTP.sent)
        # audit + ledger
        self.assertEqual(audit.tail(2)[-1]["verification"], "smtp accepted")

    # ---- TELEGRAM: receive → understand → draft → approve → send → verify -
    def test_e2e_telegram(self):
        from comms.inbox import ingest
        from comms.reply import draft_reply
        from comms.engine import send_draft
        from comms import store, audit
        from comms.registry import connectors

        conn = self._bind_telegram()
        events = conn.poll_events()
        self.assertEqual(len(events), 1)
        ing = ingest(events[0])
        self.assertTrue(ing["stored"])

        draft = draft_reply(events[0])
        draft.checks = {}
        store.store_draft(draft)
        parked = send_draft(draft, confirmed=False)
        self.assertEqual(parked["status"], "needs_approval")
        out = send_draft(draft, confirmed=True)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["verification"], "message_id 900")
        self.assertEqual(self._tg_sent[0]["chat_id"], "4242")
        self.assertEqual(audit.tail(1)[0]["platform"], "telegram")

    # ---- PHONE SOCIAL: notification → identify → draft → approved → verify
    def test_e2e_phone_social(self):
        from comms.connectors.phone_inbox import PhoneInboxConnector
        from comms.inbox import ingest, search
        from comms.reply import draft_reply
        from comms.engine import send_draft
        from comms import store
        from comms.registry import connectors
        from phone.models import ActionResult

        class FakeAdapter:
            def has(self, cmd): return True
            def run(self, cmd, *a, timeout=8):
                return ActionResult(True, "", json.dumps([{
                    "packageName": "com.whatsapp", "title": "Yasmine",
                    "content": "are we still on for friday?", "id": 9,
                    "when": 1730000000000}]))

        conn = PhoneInboxConnector(adapter=FakeAdapter())
        connectors.inject(conn)
        msgs = conn.read()
        self.assertEqual(msgs[0].platform, "social")
        self.assertEqual(msgs[0].account, "whatsapp")
        ing = ingest(msgs[0])
        self.assertTrue(ing["stored"])
        found = search("friday", platform="social")
        self.assertTrue(found)
        draft = draft_reply(msgs[0])
        draft.checks = {}
        store.store_draft(draft)
        # social send is NOT background-supported: the honest result is a
        # refusal from the connector with supervised-flow guidance — and the
        # draft never leaves without a platform that can send
        out = send_draft(draft, confirmed=True)
        self.assertFalse(out["ok"])
        self.assertIn("supervised", out.get("platform_result", "") or
                      out.get("error", "") or "")
        connectors.eject("social")
        connectors.eject("phone")

    # ---- WORKFLOW: trigger → condition → agent → tool → action → verify ---
    def test_e2e_workflow(self):
        from comms.models import UnifiedMessage
        from comms.workflow import engine
        from comms import store
        from agents.service import pool

        definition = {
            "name": "e2e-wf",
            "trigger": {"type": "email.new",
                        "match": {"urgency": {"op": "eq", "value": "urgent"}}},
            "steps": [
                {"action": "classify"},                    # understand
                {"action": "store_inbox"},                 # act: store
                {"action": "call_agent",                   # agent lane (researcher)
                 "params": {"type": "researcher", "query": "urgent deploy"}},
                {"action": "run_tool",                     # tool lane (local, safe)
                 "params": {"tool": "get_time"}},
                {"action": "notify_user"},                 # action
                {"action": "store_memory",
                 "params": {"content": "e2e workflow verified chain"}},
            ]}
        msg = UnifiedMessage(platform="email", sender="cto@corp.io",
                             content="URGENT: deploy frozen", timestamp=9.0)
        res = engine.run(definition, {"type": "email.new", "message": msg,
                                      "summary": "urgent deploy"})
        self.assertTrue(res["success"], res)
        outcomes = [s["outcome"] for s in res["steps"]]
        self.assertEqual(outcomes.count("done"), 6)
        # verification: every step carried a detail; run + pattern stored
        self.assertTrue(all(s.get("detail") is not None for s in res["steps"]))
        runs = store.recent_runs()
        self.assertTrue(any(r["success"] == 1 for r in runs))
        from knowledge.manager import KnowledgeManager
        self.assertIn("e2e-wf", KnowledgeManager().retrieve_context("e2e-wf", 5))
