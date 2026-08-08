# comms/conversation_state.py
"""Bounded, strictly-isolated conversation state.

One row per (platform, account, conversation_id). The three form a compound
key everywhere — cross-conversation/cross-account mixing is structurally
impossible in the read/write helpers, which is the wrong-recipient and
wrong-account protection this layer exists for (mission §14/§15).

State carries: participants, current topic, pending question/task, last
action, last response, pending approval draft, confidence. Everything is
update-evidence: topic/confidence change only when observed.
"""

from __future__ import annotations

import json
import time

from comms import store

_SCHEMA = """
CREATE TABLE IF NOT EXISTS comm_conv_state(
  scope TEXT PRIMARY KEY,       -- platform|account|conversation_id
  platform TEXT NOT NULL,
  account TEXT DEFAULT '',
  conversation_id TEXT NOT NULL,
  participants TEXT DEFAULT '[]',
  topic TEXT DEFAULT '',
  pending_question TEXT DEFAULT '',
  pending_task TEXT DEFAULT '',
  last_action TEXT DEFAULT '',
  last_response TEXT DEFAULT '',
  pending_approval TEXT DEFAULT '',
  confidence REAL DEFAULT 0.0,
  updated_at REAL NOT NULL
);
"""


def _init() -> None:
    with store.db()._connect() as c:
        c.executescript(_SCHEMA)


def scope_of(platform: str, account: str, conversation_id: str) -> str:
    return f"{platform}|{account or ''}|{conversation_id}"


def get(platform: str, account: str, conversation_id: str) -> dict | None:
    _init()
    rows = store.db().query("SELECT * FROM comm_conv_state WHERE scope=?",
                            (scope_of(platform, account, conversation_id),))
    if not rows:
        return None
    d = dict(rows[0])
    d["participants"] = json.loads(d.get("participants") or "[]")
    return d


def touch(platform: str, account: str, conversation_id: str, sender: str = "",
          topic: str = "", pending_question: str = "", pending_task: str = "",
          last_action: str = "", last_response: str = "",
          pending_approval: str = "", confidence: float | None = None) -> dict:
    """Upsert observed facts; never clears evidence to empty values."""
    _init()
    existing = get(platform, account, conversation_id)
    participants = list((existing or {}).get("participants") or [])
    if sender and sender not in participants:
        participants.append(sender)
    conf = confidence if confidence is not None else (existing or {}).get("confidence", 0.0)
    store.db().update(
        "INSERT OR REPLACE INTO comm_conv_state(scope,platform,account,conversation_id,"
        "participants,topic,pending_question,pending_task,last_action,last_response,"
        "pending_approval,confidence,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (scope_of(platform, account, conversation_id), platform, account or "",
         conversation_id, json.dumps(participants),
         topic or (existing or {}).get("topic", ""),
         pending_question if pending_question else (existing or {}).get("pending_question", ""),
         pending_task if pending_task else (existing or {}).get("pending_task", ""),
         last_action or (existing or {}).get("last_action", ""),
         last_response or (existing or {}).get("last_response", ""),
         pending_approval if pending_approval else (existing or {}).get("pending_approval", ""),
         conf, time.time()))
    return get(platform, account, conversation_id)


def participants_of(platform: str, account: str, conversation_id: str) -> list:
    state = get(platform, account, conversation_id)
    return list((state or {}).get("participants") or [])


def belongs(platform: str, account: str, conversation_id: str,
            recipient: str) -> bool:
    """Wrong-recipient/wrong-account guard: True iff the recipient is a KNOWN
    participant of THIS (platform, account, conversation) scope, or the scope
    is genuinely fresh and the recipient may claim it (first contact)."""
    state = get(platform, account, conversation_id)
    if state is None:
        return False  # fresh conversation: caller must not auto-send anyway
    if not state["participants"]:
        return False
    return recipient in state["participants"] or recipient == conversation_id
