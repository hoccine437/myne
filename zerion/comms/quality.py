# comms/quality.py
"""Quality telemetry → shadow mode → graduated autonomy (§30–§33).

Metrics (per platform, rolling window): drafts prepared, sends, user
accepts, user rejects/corrections, verification failures, policy blocks,
duplicates caught, loop stops, connector errors.

Graduation ladder per platform+scope:
  shadow   — observe + draft only (nothing can be sent; quality measured)
  L0..L3   — the existing approvals ladder (0 observe … 3 trusted-low-risk)

Automatic downgrade: hard evidence (verify failures, user corrections,
duplicates) forces a lower effective level until the evidence decays.
There is deliberately NO automatic upgrade: level ups require the owner
intentionally calling set_level (earned trust is recorded as evidence,
never auto-granted).
"""

from __future__ import annotations

import json
import time

from comms import store

_SCHEMA = """
CREATE TABLE IF NOT EXISTS comm_quality(
  id INTEGER PRIMARY KEY,
  ts REAL NOT NULL,
  platform TEXT NOT NULL,
  kind TEXT NOT NULL,        -- draft|send|accept|reject|verify_fail|policy_block|duplicate|loop|connector_error|correction
  detail TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS comm_shadow(
  platform TEXT PRIMARY KEY,
  state TEXT NOT NULL,       -- shadow | graduated
  started_at REAL NOT NULL,
  evidence TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS comm_autonomy(
  platform TEXT PRIMARY KEY,
  forced_max_level INTEGER,   -- NULL when unconstrained
  reason TEXT DEFAULT '',
  set_at REAL NOT NULL
);
"""


def _init() -> None:
    with store.db()._connect() as c:
        c.executescript(_SCHEMA)


def note(platform: str, kind: str, detail: str = "") -> None:
    _init()
    store.db().update("INSERT INTO comm_quality(ts,platform,kind,detail) VALUES(?,?,?,?)",
                      (time.time(), platform, kind, detail[:200]))


def metrics(platform: str, window_s: int = 86400) -> dict:
    _init()
    since = time.time() - window_s
    rows = store.db().query(
        "SELECT kind, COUNT(*) AS n FROM comm_quality WHERE platform=? AND ts>=? "
        "GROUP BY kind", (platform, since))
    m = {r["kind"]: r["n"] for r in rows}
    sends = m.get("send", 0)
    m["reply_acceptance_rate"] = round(
        m.get("accept", 0) / sends, 2) if sends else None
    m["user_correction_rate"] = round(
        (m.get("reject", 0) + m.get("correction", 0)) / max(1, m.get("draft", 1)), 2)
    m["failed_send_rate"] = round(m.get("verify_fail", 0) / sends, 2) if sends else 0
    return m


# ---- shadow mode -------------------------------------------------------

def shadow_state(platform: str) -> str:
    _init()
    rows = store.db().query("SELECT state FROM comm_shadow WHERE platform=?", (platform,))
    return rows[0]["state"] if rows else "shadow"


def set_shadow(platform: str, state: str) -> None:
    assert state in ("shadow", "graduated")
    _init()
    store.db().update(
        "INSERT OR REPLACE INTO comm_shadow(platform,state,started_at) VALUES(?,?,?)",
        (platform, state, time.time()))


def shadow_ready(platform: str, min_accepts: int = 3, max_correction: float = 0.3) -> dict:
    """Evidence a platform may leave shadow mode. Read-only assessment;
    the OWNER still flips the switch (no auto-graduation)."""
    m = metrics(platform)
    accepts = m.get("accept", 0)
    corr = m.get("user_correction_rate", 1.0) or 0.0
    ready = accepts >= min_accepts and corr <= max_correction
    return {"ready": ready, "metrics": m, "accepts": accepts,
            "correction_rate": corr}


# ---- automatic downgrade (never upgrade) --------------------------------

_DEGRADE_RULES = (  # (kind, threshold in window, forced max level)
    ("verify_fail", 2, 2),       # verification failures → never above confirmation
    ("correction", 3, 1),        # repeated user corrections → drafting only
    ("duplicate", 2, 1),         # duplicate sends got through → drafting only
    ("loop", 1, 1),              # any loop stop → drafting until user clears
    ("connector_error", 3, 1),
)


def apply_quality_gates(platform: str) -> dict:
    """Evaluate rules; persist the strongest active downgrade. Returns the
    current constraint. This only ever LOWERS; resets are explicit owner
    action via approvals.set_level + comm_autonomy clear."""
    _init()
    m_raw = {r["kind"]: r["n"] for r in store.db().query(
        "SELECT kind, COUNT(*) AS n FROM comm_quality WHERE platform=? AND ts>=?",
        (platform, time.time() - 86400))}
    forced, reason = None, ""
    for kind, threshold, level in _DEGRADE_RULES:
        if m_raw.get(kind, 0) >= threshold:
            candidate = level
            if forced is None or candidate < forced:
                forced = candidate
                reason = f"{kind}×{m_raw[kind]} in 24h → max level {level}"
    if forced is not None:
        store.db().update(
            "INSERT OR REPLACE INTO comm_autonomy(platform,forced_max_level,reason,set_at) "
            "VALUES(?,?,?,?)", (platform, forced, reason, time.time()))
    return {"platform": platform, "forced_max_level": forced, "reason": reason}


def forced_max(platform: str) -> dict:
    _init()
    rows = store.db().query(
        "SELECT forced_max_level, reason FROM comm_autonomy WHERE platform=?",
        (platform,))
    if rows:
        return {"forced_max_level": rows[0]["forced_max_level"], "reason": rows[0]["reason"]}
    return {"forced_max_level": None}


def clear_downgrade(platform: str) -> None:
    _init()
    store.db().update("DELETE FROM comm_autonomy WHERE platform=?", (platform,))
