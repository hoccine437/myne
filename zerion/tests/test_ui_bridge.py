# tests/test_ui_bridge.py
"""WebUI bridge tests.

Verifies that the UI layer (ui/) talks to the Core correctly without
touching business logic:

* the session mirrors main.py's turn handling for local paths
  (command palette, mute, confirmations) with engine calls intact
* every Core effect is surfaced as a structured event on the bus
* the HTTP/WS surface serves and routes properly

No API key, no network: the LLM path is deliberately CPU-free here —
its absence is a valid, graceful production state the Core handles.
"""

import json
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from ui.events import bus  # noqa: E402
from ui.session import ZerionUISession  # noqa: E402


def drain_events(types=None, limit=400):
    events = bus.replay()
    if types:
        events = [e for e in events if e["type"] in types]
    return events[-limit:]


class UISessionTests(unittest.TestCase):
    def setUp(self):
        self.session = ZerionUISession()
        self._marker = bus.replay()[-1]["seq"] if bus.replay() else 0

    def fresh(self, *types):
        return [e for e in bus.replay(since_seq=self._marker) if not types or e["type"] in types]

    def test_command_palette_turn_emits_chat_and_stays_local(self):
        self.session.process_message("/help")
        chats = [e for e in self.fresh("chat") if e["data"].get("role") == "ai"]
        self.assertTrue(chats, "expected an AI chat event")
        self.assertIn("/status", chats[-1]["data"]["text"])
        # a full turn lifecycle happened
        turns = [e["data"].get("phase") for e in self.fresh("turn")]
        self.assertIn("start", turns)
        self.assertIn("end", turns)

    def test_mute_resets_session(self):
        self.session.state.set_last_user_text("remember me")
        self.session.process_message("mute")
        self.assertEqual(self.session.state.conversation_history, [])

    def test_unknown_chat_gracefully_reaches_llm_fallback(self):
        # Without GEMINI_API_KEY the Core returns its own graceful
        # fallback string; the UI must relay it, kind-tag the stages and
        # emit core_state transitions — never crash.
        self.session.process_message("hello there")
        texts = [e["data"]["text"] for e in self.fresh("chat") if e["data"].get("role") == "ai"]
        self.assertTrue(any(t.strip() for t in texts), "expected a non-empty AI reply")
        stages = [e["data"]["stage"] for e in self.fresh("stage")]
        self.assertIn("context", stages)
        self.assertIn("intent", stages)
        states = [e["data"]["state"] for e in self.fresh("core_state")]
        self.assertIn("thinking", states)
        self.assertIn("idle", states)

    def test_tool_confirmation_flow_via_ui(self):
        # run_shell stands in for any destructive tool: first call arms
        # a pending confirmation, confirm() executes it.
        self.session.run_terminal_command("echo ui-bridge-test")
        import time
        deadline = time.time() + 5
        while time.time() < deadline:
            if any(e["type"] == "confirm_required" and e["data"].get("pending")
                   for e in self.fresh()):
                break
            time.sleep(0.05)
        self.assertTrue(
            any(e["type"] == "confirm_required" and e["data"].get("pending")
                for e in self.fresh()),
            "expected confirm_required event for destructive terminal command")

        baseline = bus.replay()[-1]["seq"]
        self._marker = baseline
        self.session.confirm()
        ends = [e for e in self.fresh("tool") if e["data"].get("phase") == "end"]
        self.assertTrue(ends, "expected tool end event after confirm")
        self.assertTrue(ends[-1]["data"]["success"])
        self.assertIn("ui-bridge-test", ends[-1]["data"].get("output", ""))

    def test_cancel_clears_pending(self):
        from tools.manager import tool_manager
        tool_manager.execute("delete_file", {"path": "/tmp/zerion-ui-test-should-not-exist"})
        self.assertTrue(tool_manager.has_pending_confirmation())
        self.session._set_pending_origin("terminal")
        self.session.cancel()
        self.assertFalse(tool_manager.has_pending_confirmation())

    def test_busy_guard_rejects_overlapping_turns(self):
        with self.session._lock:
            self.session._busy = True
        self.session.process_message("/help")
        notes = self.fresh("notification")
        self.assertTrue(any("busy" in (e["data"].get("text") or "").lower() for e in notes))

    def test_workspace_mapping(self):
        from ui.session import _workspace_for
        from intent.classifier import classify
        self.assertEqual(_workspace_for(classify("run python print(1)"), "run python print(1)"), "coding")
        c = classify("read the file notes.txt")
        self.assertIn(_workspace_for(c, "read the file notes.txt"), ("research", "coding"))
        self.assertEqual(_workspace_for(classify("what's my name"), "what's my name"), "research")
        self.assertEqual(_workspace_for(classify("hello"), "hello"), "chat")
        self.assertEqual(_workspace_for(classify("hello"), "check the btc price chart"), "trading")


class UIServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from ui.server import app
        cls.client = TestClient(app)

    def test_bootstrap(self):
        r = self.client.get("/api/bootstrap")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("version", data)
        self.assertIsInstance(data["tools"], list)
        self.assertIn("model", data["settings"])
        # the API key (or any secret value) is never serialized to clients;
        # config *warnings* may name env var keys but must carry no values
        self.assertNotIn("GEMINI_API_KEY", json.dumps(data["settings"]))
        self.assertIsNone(data["settings"].get("api_key"))
        for warning in data.get("config_warnings", []):
            self.assertNotIn("=", warning.split("—")[0], f"warning leaks assignment: {warning}")

    def test_index_served(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Zerion", r.content)
        self.assertIn(b'/static/js/main.js', r.content)

    def test_fs_list_through_core_tool(self):
        r = self.client.get("/api/fs/list", params={"path": "."})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any(e["name"] == "main.py" for e in r.json()["entries"]))

    def test_fs_read_through_core_tool(self):
        r = self.client.get("/api/fs/read", params={"path": "VERSION"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["content"].strip())

    def test_fs_missing_is_404(self):
        r = self.client.get("/api/fs/read", params={"path": "/definitely/missing"})
        self.assertEqual(r.status_code, 404)

    def test_settings_runtime_toggle(self):
        r = self.client.post("/api/settings", json={"planner_enabled": True})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["planner_enabled"])
        r2 = self.client.post("/api/settings", json={"planner_enabled": False})
        self.assertFalse(r2.json()["planner_enabled"])
        # unknown keys are rejected, not swallowed
        r3 = self.client.post("/api/settings", json={"gemini_api_key": "nope"})
        self.assertIn("gemini_api_key", r3.json().get("rejected", []))

    def test_memory_endpoint_shape(self):
        r = self.client.get("/api/memory")
        self.assertEqual(r.status_code, 200)
        self.assertIn("memory", r.json())
        self.assertIn("stats", r.json())


if __name__ == "__main__":
    unittest.main()
