# comms/outbox.py
"""Offline-safe outbound queue.

QUEUE → DEDUPLICATE → WAIT → RECHECK → EXECUTE ONLY IF STILL VALID.

Each queued item has expiry + error classification:
  temporary  → retry with exponential backoff (bounded attempts)
  auth/permission/unknown → STOP + report (no blind retries)
  expired     → dropped with audit trail
Every re-execution revalidates policy + recipient + content freshness BEFORE
re-claiming its action key (crash recovery never blindly replays).
"""

from __future__ import annotations

import time
import uuid

from comms import audit, store

_SCHEMA = """
CREATE TABLE IF NOT EXISTS comm_outbox(
  queue_id TEXT PRIMARY KEY,
  draft_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  account TEXT DEFAULT '',
  recipient TEXT DEFAULT '',
  status TEXT NOT NULL,        -- queued | revalidated | sent | failed | expired | dropped
  attempts INTEGER DEFAULT 0,
  next_retry_at REAL DEFAULT 0,
  expires_at REAL NOT NULL,
  last_error TEXT DEFAULT '',
  created_at REAL NOT NULL
);
"""

DEFAULT_TTL = 24 * 3600
MAX_ATTEMPTS = 5


def _init():
    with store.db()._connect() as c:
        c.executescript(_SCHEMA)


def classify_error(text: str) -> str:
    t = (text or "").lower()
    if any(w in t for w in ("timeout", "timed out", "temporarily", "connection",
                            "unavailable", "429", "rate limit", "503", "502")):
        return "temporary"
    if any(w in t for w in ("auth", "credential", "login", "unauthorized",
                            "401", "403", "invalid token")):
        return "auth"
    if any(w in t for w in ("permission", "forbidden", "not allowed",
                            "policy", "denied")):
        return "permission"
    return "unknown"


def enqueue(draft_id: str, platform: str, account: str, recipient: str,
            ttl: int = DEFAULT_TTL) -> str:
    _init()
    qid = uuid.uuid4().hex[:12]
    store.db().update(
        "INSERT INTO comm_outbox(queue_id,draft_id,platform,account,recipient,status,"
        "expires_at,created_at) VALUES(?,?,?,?,?,'queued',?,?)",
        (qid, draft_id, platform, account, recipient, time.time() + ttl, time.time()))
    audit.record("queue", platform, account=account, target=recipient,
                 result="queued", extra={"queue_id": qid})
    return qid


def pending(limit: int = 25) -> list:
    _init()
    now = time.time()
    handle = store.db()
    expired = handle.query(
        "SELECT queue_id FROM comm_outbox WHERE status IN ('queued','revalidated') "
        "AND expires_at<?", (now,))
    for row in expired:
        handle.update("UPDATE comm_outbox SET status='expired', last_error=? WHERE queue_id=?",
                      ("ttl reached before execution", row["queue_id"]))
        audit.record("queue", "", target=row["queue_id"], result="expired")
    return [dict(r) for r in handle.query(
        "SELECT * FROM comm_outbox WHERE status IN ('queued','revalidated') "
        "AND next_retry_at<=? ORDER BY created_at LIMIT ?", (now, limit))]


def mark(queue_id: str, status: str, error: str = "", backoff: bool = False) -> None:
    _init()
    handle = store.db()
    rows = handle.query("SELECT attempts FROM comm_outbox WHERE queue_id=?", (queue_id,))
    if not rows:
        return
    attempts = rows[0]["attempts"] + (1 if status in ("queued", "failed") else 0)
    next_retry = 0.0
    if backoff:
        # exponential: 30s, 60s, 120s... capped at 1h, budget-bounded
        delay = min(3600, 30 * (2 ** attempts))
        next_retry = time.time() + delay
    handle.update(
        "UPDATE comm_outbox SET status=?, attempts=?, next_retry_at=?, last_error=? "
        "WHERE queue_id=?",
        (status, attempts, next_retry, error[:200], queue_id))


def flush(executor) -> dict:
    """Run due queue items through `executor(row_dict) -> dict(ok, result, error).
    The executor is comms.engine.send_queued_draft (revalidates everything).
    Returns counts."""
    _init()
    done = {"executed": 0, "retried": 0, "stopped": 0, "expired": 0}
    for row in pending():
        if row["attempts"] >= MAX_ATTEMPTS:
            mark(row["queue_id"], "dropped", "retry budget exhausted")
            done["stopped"] += 1
            audit.record("queue", row["platform"], target=row["recipient"],
                         result="dropped", error="retry budget exhausted",
                         extra={"queue_id": row["queue_id"]})
            continue
        outcome = executor(row)
        if outcome.get("ok"):
            mark(row["queue_id"], "sent")
            done["executed"] += 1
            continue
        error_class = classify_error(outcome.get("error", ""))
        if error_class == "temporary":
            mark(row["queue_id"], "queued", outcome.get("error", ""), backoff=True)
            done["retried"] += 1
        else:
            mark(row["queue_id"], "failed", outcome.get("error", ""))
            done["stopped"] += 1
            audit.record("queue", row["platform"], target=row["recipient"],
                         result="failed", error=f"{error_class}: {outcome.get('error','')}",
                         extra={"queue_id": row["queue_id"]})
    return done
