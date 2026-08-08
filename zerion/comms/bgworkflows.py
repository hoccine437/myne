# comms/bgworkflows.py
"""Authorized background communication workflows — the explicit permission
object that makes "reply to people on Instagram" a bounded legal thing.

A flow row carries: id, platform, account, scope, allowed_actions, risk
level, status, authorization_source ('user-command' only — workflows NEVER
spawn from events/agents on their own), enabled/expires timestamps, and
last_activity so staleness is observable.

Semantics that matter:
  * flows EXPIRE (default 24h, owner-tunable) — a single sentence is not
    permanent authorization
  * stop is immediate: status flips to 'stopped'; the autopilot gate checks
    this table before drafting anything, so stopping takes effect on the
    very next event
  * autonomous replies additionally require the flow AND the approvals
    ladder to say 'auto' (layers multiply, never cancel)
"""

from __future__ import annotations

import json
import time
import uuid

from comms import audit, store

_SCHEMA = """
CREATE TABLE IF NOT EXISTS comm_bg_flows(
  flow_id TEXT PRIMARY KEY,
  platform TEXT NOT NULL,
  account TEXT DEFAULT '',
  scope TEXT NOT NULL DEFAULT 'messages',
  allowed_actions TEXT NOT NULL DEFAULT '["draft","reply"]',
  risk_level TEXT NOT NULL DEFAULT 'low',
  status TEXT NOT NULL DEFAULT 'active',
  authorization_source TEXT NOT NULL DEFAULT 'user-command',
  enabled_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  last_activity REAL DEFAULT 0
);
"""


def _init() -> None:
    with store.db()._connect() as c:
        c.executescript(_SCHEMA)


def start(platform: str, account: str = "", scope: str = "messages",
          actions=None, risk_level: str = "low", ttl_s: int = 86400) -> dict:
    """Create an ACTIVE authorized flow (the caller has already collected
    the user's confirmation — bg flow start is a confirm handshake in the
    command layer)."""
    _init()
    fid = uuid.uuid4().hex[:10]
    now = time.time()
    store.db().update(
        "INSERT INTO comm_bg_flows(flow_id,platform,account,scope,allowed_actions,"
        "risk_level,status,authorization_source,enabled_at,expires_at,last_activity) "
        "VALUES(?,?,?,?,?,?,'active','user-command',?,?,?)",
        (fid, platform, account or "", scope,
         json.dumps(actions or ["draft", "reply"]), risk_level, now,
         now + ttl_s, now))
    audit.record("bg_flow_start", platform, account=account,
                 workflow=fid, result="active",
                 extra={"scope": scope, "ttl_s": ttl_s})
    return get(fid)


def get(flow_id: str) -> dict | None:
    _init()
    rows = store.db().query("SELECT * FROM comm_bg_flows WHERE flow_id=?", (flow_id,))
    if not rows:
        return None
    d = dict(rows[0])
    d["allowed_actions"] = json.loads(d.get("allowed_actions") or "[]")
    return d


def stop(flow_id: str = "", platform: str = "") -> int:
    """Immediate stop (mission §2). Returns the number of flows stopped."""
    _init()
    if flow_id:
        rows = store.db().query("SELECT flow_id FROM comm_bg_flows "
                                "WHERE flow_id=? AND status='active'", (flow_id,))
        ids = [r["flow_id"] for r in rows]
    elif platform:
        ids = [r["flow_id"] for r in store.db().query(
            "SELECT flow_id FROM comm_bg_flows WHERE platform=? AND status='active'",
            (platform,))]
    else:
        ids = [r["flow_id"] for r in store.db().query(
            "SELECT flow_id FROM comm_bg_flows WHERE status='active'")]
    for fid in ids:
        store.db().update("UPDATE comm_bg_flows SET status='stopped' WHERE flow_id=?",
                          (fid,))
        audit.record("bg_flow_stop", "", workflow=fid, result="stopped")
    return len(ids)


def active(flow_id: str = "", platform: str = "") -> list:
    """Currently-live flows (auto-expires first). Read-only for the gates."""
    _init()
    now = time.time()
    expired = store.db().query(
        "SELECT flow_id FROM comm_bg_flows WHERE status='active' AND expires_at<?",
        (now,))
    for r in expired:
        store.db().update("UPDATE comm_bg_flows SET status='expired' WHERE flow_id=?",
                          (r["flow_id"],))
    sql = "SELECT * FROM comm_bg_flows WHERE status='active'"
    args = []
    if flow_id:
        sql += " AND flow_id=?"; args.append(flow_id)
    if platform:
        sql += " AND platform=?"; args.append(platform)
    out = []
    for r in store.db().query(sql, tuple(args)):
        d = dict(r)
        d["allowed_actions"] = json.loads(d.get("allowed_actions") or "[]")
        out.append(d)
    return out


def covers(platform: str, account: str = "", scope: str = "messages") -> dict | None:
    """The autopilot's authorization probe: a matching ACTIVE unexpired
    flow, marking activity. None = no background authorization."""
    for flow in active(platform=platform):
        if account and flow["account"] and flow["account"] != account:
            continue
        if flow["scope"] != scope:
            continue
        store.db().update("UPDATE comm_bg_flows SET last_activity=? WHERE flow_id=?",
                          (time.time(), flow["flow_id"]))
        return flow
    return None


def list_all(limit: int = 50) -> list:
    _init()
    active()  # expire lazily
    rows = store.db().query(
        "SELECT * FROM comm_bg_flows ORDER BY enabled_at DESC LIMIT ?", (limit,))
    out = []
    for r in rows:
        d = dict(r)
        d["allowed_actions"] = json.loads(d.get("allowed_actions") or "[]")
        out.append(d)
    return out
