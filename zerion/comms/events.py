# comms/events.py
"""Event identity + exactly-once processing registry.

Every inbound item produces an Event with a deterministic id BEFORE any
processing decision. Processing is lock-then-record: the processing-log row
is written first (status 'processing'), so a crash mid-pipeline is detected
and revalidated on recovery instead of blindly replayed, and duplicate
deliveries hit UNIQUE conflicts and are ignored.

Outbound actions get the same guard: an action fingerprint that has already
reached 'sent' is never executed again.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field

from comms import store

_SCHEMA = """
CREATE TABLE IF NOT EXISTS comm_event_log(
  event_id TEXT PRIMARY KEY,
  platform TEXT NOT NULL,
  conversation_id TEXT DEFAULT '',
  seen_at REAL NOT NULL,
  status TEXT NOT NULL,           -- processing | done | failed | ignored
  result TEXT DEFAULT '',
  attempts INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS comm_action_log(
  action_key TEXT PRIMARY KEY,    -- idempotency fingerprint for outbound work
  platform TEXT NOT NULL,
  target TEXT DEFAULT '',
  status TEXT NOT NULL,           -- executing | sent | failed | dropped
  first_at REAL NOT NULL,
  last_at REAL NOT NULL,
  result TEXT DEFAULT ''
);
"""


def init() -> None:
    handle = store.db()
    with handle._connect() as c:
        c.executescript(_SCHEMA)


@dataclass
class Event:
    platform: str
    conversation_id: str = ""
    event_id: str = ""
    seen_at: float = field(default_factory=time.time)

    @staticmethod
    def key_for(platform: str, account: str, sender: str,
                conversation_id: str, platform_message_id: str,
                content: str, ts: float) -> str:
        """Deterministic identity: platform message id when present, else a
        content+timestamp fingerprint of this exact item."""
        if platform_message_id:
            base = f"{platform}|{account}|msg:{platform_message_id}"
        else:
            base = (f"{platform}|{account}|{sender}|{conversation_id}|"
                    f"{content[:160]}|{int(ts)}")
        return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]


def claim_event(event_id: str, platform: str, conversation_id: str) -> str:
    """Returns 'new' (processing claimed) | 'duplicate'|'reprocess'.
    'reprocess' = a previous run crashed mid-processing; callers must
    revalidate, not replay."""
    init()
    handle = store.db()
    rows = handle.query("SELECT status FROM comm_event_log WHERE event_id=?",
                        (event_id,))
    if rows:
        prev = rows[0]["status"]
        if prev in ("done", "ignored"):
            return "duplicate"
        if prev == "processing":
            handle.update(
                "UPDATE comm_event_log SET attempts=attempts+1 WHERE event_id=?",
                (event_id,))
            return "reprocess"
        handle.update(
            "UPDATE comm_event_log SET status='processing', attempts=attempts+1 WHERE event_id=?",
            (event_id,))
        return "reprocess"
    with handle._connect() as c:
        c.execute("INSERT INTO comm_event_log(event_id,platform,conversation_id,"
                  "seen_at,status) VALUES(?,?,?,?,?)",
                  (event_id, platform, conversation_id, time.time(), "processing"))
    return "new"


def settle_event(event_id: str, status: str, result: str = "") -> None:
    init()
    store.db().update("UPDATE comm_event_log SET status=?, result=? WHERE event_id=?",
                      (status, result[:200], event_id))


def action_key(platform: str, account: str, target: str, body: str,
               action: str = "send") -> str:
    raw = f"{action}|{platform}|{account}|{target}|{content_norm(body)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def content_norm(body: str) -> str:
    return " ".join((body or "").split()).lower()[:500]


def claim_action(key: str, platform: str, target: str) -> bool:
    """True = this action fingerprint is being executed for the first time.
    'executing' leftovers from a crash return True again ONLY after the
    caller revalidates (outbox does that before re-claiming)."""
    init()
    handle = store.db()
    rows = handle.query("SELECT status FROM comm_action_log WHERE action_key=?",
                        (key,))
    if rows and rows[0]["status"] in ("sent", "executing"):
        return False
    with handle._connect() as c:
        c.execute("INSERT OR REPLACE INTO comm_action_log(action_key,platform,"
                  "target,status,first_at,last_at) VALUES(?,?,?,?,?,?)",
                  (key, platform, target, "executing",
                   rows[0]["first_at"] if "rows" in dir() and rows else time.time(),
                   time.time()))
    return True


def settle_action(key: str, status: str, result: str = "") -> None:
    init()
    store.db().update(
        "UPDATE comm_action_log SET status=?, last_at=?, result=? WHERE action_key=?",
        (status, time.time(), result[:200], key))
