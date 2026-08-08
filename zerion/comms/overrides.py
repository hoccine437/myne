# comms/overrides.py
"""User override plane (mission §28) — the owner is always in charge.

Operations:
  pause_all / resume               — global autonomous hold (sends park)
  estop                            — STOP ALL EXTERNAL ACTIONS (queue cleared,
                                     autonomous halted, needs resume to heal)
  disable_platform / enable_platform
  disable_contact / enable_contact — per-sender hold
  disable_workflow / enable_workflow
  clear_queue                      — expire pending outbox items honestly

Checks are consulted by the decision gate and the send engine. Overrides
persist in the DB (restart-proof) and audit every state change.
"""

from __future__ import annotations

import time

from comms import audit, store

_SCHEMA = """
CREATE TABLE IF NOT EXISTS comm_overrides(
  key TEXT PRIMARY KEY,        -- 'paused' | 'estop' | 'platform:email' | 'contact:a@b' | 'workflow:wf1'
  state TEXT NOT NULL,         -- 'active' | 'off'
  reason TEXT DEFAULT '',
  updated_at REAL NOT NULL
);
"""


def _init() -> None:
    with store.db()._connect() as c:
        c.executescript(_SCHEMA)


def _set(key: str, state: str, reason: str = "") -> None:
    _init()
    store.db().update(
        "INSERT OR REPLACE INTO comm_overrides(key,state,reason,updated_at) VALUES(?,?,?,?)",
        (key, state, reason[:200], time.time()))
    audit.record("override", "", target=key, result=state, error="", extra={"reason": reason[:200]})


def _get(key: str) -> str | None:
    _init()
    rows = store.db().query("SELECT state FROM comm_overrides WHERE key=?", (key,))
    return rows[0]["state"] if rows else None


# -- user operations -----------------------------------------------------

def pause_all(reason: str = "user pause") -> dict:
    _set("paused", "active", reason)
    return {"paused": True}


def resume() -> dict:
    _set("paused", "off")
    _set("estop", "off")
    return {"paused": False, "estop": False}


def estop(reason: str = "emergency stop") -> dict:
    """Emergency: stop all external actions immediately and expire the queue."""
    _set("estop", "active", reason)
    _set("paused", "active", reason)
    dropped = clear_queue(reason="estop")
    return {"estop": True, "queue_dropped": dropped}


def clear_queue(reason: str = "user") -> int:
    _init()
    try:
        from comms import outbox  # schema owner — init before touching its tables
        outbox._init()
    except Exception:
        return 0
    rows = store.db().query(
        "SELECT queue_id FROM comm_outbox WHERE status IN ('queued','revalidated')")
    for r in rows:
        store.db().update(
            "UPDATE comm_outbox SET status='dropped', last_error=? WHERE queue_id=?",
            (f"dropped by {reason}", r["queue_id"]))
    return len(rows)


def disable_platform(platform: str, reason: str = "") -> dict:
    _set(f"platform:{platform}", "active", reason)
    return {platform: "disabled"}


def enable_platform(platform: str) -> dict:
    _set(f"platform:{platform}", "off")
    return {platform: "enabled"}


def disable_contact(identifier: str, reason: str = "") -> dict:
    _set(f"contact:{identifier}", "active", reason)
    return {identifier: "disabled"}


def enable_contact(identifier: str) -> dict:
    _set(f"contact:{identifier}", "off")
    return {identifier: "enabled"}


def disable_workflow(workflow_id: str, reason: str = "") -> dict:
    _set(f"workflow:{workflow_id}", "active", reason)
    store.db().update("UPDATE comm_workflows SET enabled=0 WHERE workflow_id=?",
                      (workflow_id,))
    return {workflow_id: "disabled"}


def enable_workflow(workflow_id: str) -> dict:
    _set(f"workflow:{workflow_id}", "off")
    store.db().update("UPDATE comm_workflows SET enabled=1 WHERE workflow_id=?",
                      (workflow_id,))
    return {workflow_id: "enabled"}


# -- queries used by the gates -------------------------------------------

def is_paused() -> bool:
    return _get("paused") == "active" or _get("estop") == "active"


def is_estopped() -> bool:
    return _get("estop") == "active"


def platform_disabled(platform: str) -> bool:
    return _get(f"platform:{platform}") == "active"


def contact_disabled(identifier: str) -> bool:
    return _get(f"contact:{identifier}") == "active"


def workflow_disabled(workflow_id: str) -> bool:
    return _get(f"workflow:{workflow_id}") == "active"


def status() -> dict:
    return {
        "paused": is_paused(), "estop": is_estopped(),
    }
