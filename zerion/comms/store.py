# comms/store.py
"""Communication persistence — tables created on the SAME SQLite database
file zerion already uses (knowledge/zerion_knowledge.db). The knowledge
schema is untouched; comm tables are additive, prefixed comm_*, and created
idempotently at import of any store user (CREATE TABLE IF NOT EXISTS).

WAL mode + the Database wrapper's crash behavior apply to these tables too.
Secrets (EMAIL_PASSWORD, tokens) are NEVER written here — audit and send
ledgers carry action metadata only.
"""

from __future__ import annotations

import json
import time
import uuid

from knowledge.database import Database

_SCHEMA = """
CREATE TABLE IF NOT EXISTS comm_messages(
  id INTEGER PRIMARY KEY,
  stable_id TEXT UNIQUE,
  platform TEXT NOT NULL,
  account TEXT DEFAULT '',
  sender TEXT DEFAULT '',
  recipients TEXT DEFAULT '[]',
  timestamp REAL NOT NULL,
  content TEXT DEFAULT '',
  attachments TEXT DEFAULT '[]',
  conversation_id TEXT DEFAULT '',
  reply_context TEXT DEFAULT '',
  classification TEXT DEFAULT '',
  urgency TEXT DEFAULT '',
  status TEXT DEFAULT 'received',
  permissions TEXT DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_comm_msg_platform ON comm_messages(platform, timestamp);
CREATE INDEX IF NOT EXISTS idx_comm_msg_conv ON comm_messages(conversation_id);
CREATE TABLE IF NOT EXISTS comm_drafts(
  draft_id TEXT PRIMARY KEY,
  platform TEXT NOT NULL,
  account TEXT DEFAULT '',
  recipient TEXT DEFAULT '',
  subject TEXT DEFAULT '',
  body TEXT DEFAULT '',
  conversation_id TEXT DEFAULT '',
  in_reply_to TEXT DEFAULT '',
  tone TEXT DEFAULT 'casual',
  generated_locally INTEGER DEFAULT 0,
  checks TEXT DEFAULT '{}',
  risk_markers TEXT DEFAULT '[]',
  status TEXT DEFAULT 'prepared',
  created_at REAL NOT NULL,
  decided_at REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS comm_contacts(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  identifiers TEXT NOT NULL DEFAULT '[]',
  platforms TEXT NOT NULL DEFAULT '[]',
  notes TEXT DEFAULT '',
  last_topic TEXT DEFAULT '',
  pending_tasks TEXT DEFAULT '[]',
  updated_at REAL NOT NULL,
  UNIQUE(name)
);
CREATE TABLE IF NOT EXISTS comm_events(
  event_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  start REAL NOT NULL,
  end REAL NOT NULL,
  attendees TEXT DEFAULT '[]',
  location TEXT DEFAULT '',
  notes TEXT DEFAULT '',
  status TEXT DEFAULT 'confirmed',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comm_events_start ON comm_events(start);
CREATE TABLE IF NOT EXISTS comm_send_log(
  id INTEGER PRIMARY KEY,
  ts REAL NOT NULL,
  platform TEXT NOT NULL,
  recipient TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  draft_id TEXT DEFAULT '',
  result TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_comm_send_ts ON comm_send_log(ts);
CREATE TABLE IF NOT EXISTS comm_policy(
  scope TEXT PRIMARY KEY,     -- 'platform:email' | 'account:..@..'
  level INTEGER NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS comm_workflows(
  workflow_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  definition TEXT NOT NULL,
  enabled INTEGER DEFAULT 1,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS comm_workflow_runs(
  run_id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  trigger_summary TEXT DEFAULT '',
  steps TEXT DEFAULT '[]',
  success INTEGER DEFAULT 0,
  started REAL NOT NULL,
  finished REAL DEFAULT 0,
  error TEXT DEFAULT ''
);
"""

_POPULATED = False


def db() -> Database:
    """One shared handle; schema applied once per process."""
    global _POPULATED
    handle = Database()
    if not _POPULATED:
        with handle._connect() as c:
            c.executescript(_SCHEMA)
        _POPULATED = True
    return handle


def _dump(value) -> str:
    return json.dumps(value, default=str)


def _load(raw, default):
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or default)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# messages (unified inbox)
# ---------------------------------------------------------------------------

def store_message(msg) -> int:
    """Idempotent by stable_id; returns row id (0 if duplicate)."""
    handle = db()
    with handle._connect() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO comm_messages(stable_id,platform,account,sender,"
            "recipients,timestamp,content,attachments,conversation_id,reply_context,"
            "classification,urgency,status,permissions) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (msg.stable_id(), msg.platform, msg.account, msg.sender,
             _dump(list(msg.recipients)), msg.timestamp, msg.content,
             _dump(list(msg.attachments)), msg.conversation_id, msg.reply_context,
             msg.classification, msg.urgency, msg.status, _dump(list(msg.permissions))))
        return cur.lastrowid or 0


def set_message_status(stable_id: str, status: str) -> None:
    db().update("UPDATE comm_messages SET status=? WHERE stable_id=?", (status, stable_id))


def query_messages(where: str = "", params: tuple = (), limit: int = 100,
                   order: str = "timestamp DESC") -> list:
    sql = "SELECT * FROM comm_messages" + (f" WHERE {where}" if where else "") + \
          f" ORDER BY {order} LIMIT ?"
    rows = db().query(sql, (*params, int(limit)))
    out = []
    for r in rows:
        d = dict(r)
        for k in ("recipients", "attachments", "permissions"):
            d[k] = _load(d.get(k), [])
        out.append(d)
    return out


def conversation_history(conversation_id: str, limit: int = 10) -> list:
    return query_messages("conversation_id=?", (conversation_id,), limit,
                          order="timestamp ASC")


# ---------------------------------------------------------------------------
# drafts
# ---------------------------------------------------------------------------

def store_draft(draft) -> None:
    handle = db()
    handle.update(
        "INSERT OR REPLACE INTO comm_drafts(draft_id,platform,account,recipient,subject,"
        "body,conversation_id,in_reply_to,tone,generated_locally,checks,risk_markers,"
        "status,created_at,decided_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (draft.draft_id, draft.platform, draft.account, draft.recipient, draft.subject,
         draft.body, draft.conversation_id, draft.in_reply_to, draft.tone,
         1 if draft.generated_locally else 0, _dump(draft.checks),
         _dump(list(draft.risk_markers)), draft.status, draft.created_at, 0))


def get_draft(draft_id: str) -> dict | None:
    rows = db().query("SELECT * FROM comm_drafts WHERE draft_id=?", (draft_id,))
    if not rows:
        return None
    d = dict(rows[0])
    d["checks"] = _load(d.get("checks"), {})
    d["risk_markers"] = _load(d.get("risk_markers"), [])
    return d


def set_draft_status(draft_id: str, status: str) -> None:
    db().update("UPDATE comm_drafts SET status=?, decided_at=? WHERE draft_id=?",
                (status, time.time(), draft_id))


def pending_drafts() -> list:
    rows = db().query(
        "SELECT * FROM comm_drafts WHERE status IN ('prepared','needs_approval') "
        "ORDER BY created_at DESC")
    out = []
    for r in rows:
        d = dict(r)
        d["checks"] = _load(d.get("checks"), {})
        d["risk_markers"] = _load(d.get("risk_markers"), [])
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# contacts (minimal, purpose-bound: communication context only)
# ---------------------------------------------------------------------------

def upsert_contact(name: str, identifier: str = "", platform: str = "",
                   notes: str = "") -> None:
    rows = db().query("SELECT * FROM comm_contacts WHERE name=?", (name,))
    now = time.time()
    if not rows:
        db().update(
            "INSERT INTO comm_contacts(name,identifiers,platforms,notes,updated_at) "
            "VALUES(?,?,?,?,?)",
            (name, _dump([identifier] if identifier else []),
             _dump([platform] if platform else []), notes, now))
        return
    identifiers = _load(rows[0]["identifiers"], [])
    platforms = _load(rows[0]["platforms"], [])
    if identifier and identifier not in identifiers:
        identifiers.append(identifier)
    if platform and platform not in platforms:
        platforms.append(platform)
    db().update(
        "UPDATE comm_contacts SET identifiers=?, platforms=?, "
        "notes=CASE WHEN ?='' THEN notes ELSE ? END, updated_at=? WHERE name=?",
        (_dump(identifiers), _dump(platforms), notes, notes, now, name))


def find_contact(query: str) -> dict | None:
    q = (query or "").strip().lower()
    if not q:
        return None
    for r in db().query("SELECT * FROM comm_contacts"):
        d = dict(r)
        ids = _load(d["identifiers"], [])
        if q == d["name"].lower() or any(q == str(i).lower() for i in ids):
            d["identifiers"] = ids
            d["platforms"] = _load(d["platforms"], [])
            d["pending_tasks"] = _load(d.get("pending_tasks"), [])
            return d
    return None


def contact_note(name: str, topic: str) -> None:
    db().update("UPDATE comm_contacts SET last_topic=?, updated_at=? WHERE name=?",
                (topic[:200], time.time(), name))
    if not find_contact(name):
        upsert_contact(name)


def list_contacts(limit: int = 100) -> list:
    return [dict(r) for r in db().query(
        "SELECT * FROM comm_contacts ORDER BY updated_at DESC LIMIT ?", (limit,))]


# ---------------------------------------------------------------------------
# calendar events
# ---------------------------------------------------------------------------

def create_event(title: str, start: float, end: float, attendees=None,
                 location: str = "", notes: str = "") -> str:
    eid = uuid.uuid4().hex[:10]
    db().update(
        "INSERT INTO comm_events(event_id,title,start,end,attendees,location,notes,"
        "created_at) VALUES(?,?,?,?,?,?,?,?)",
        (eid, title, float(start), float(end), _dump(attendees or []),
         location, notes, time.time()))
    return eid


def list_events(from_ts: float = 0.0, to_ts: float = 0.0, limit: int = 50) -> list:
    to_ts = to_ts or (from_ts + 31 * 86400 if from_ts else time.time() + 31 * 86400)
    rows = db().query(
        "SELECT * FROM comm_events WHERE status!='cancelled' AND end>=? AND start<=? "
        "ORDER BY start LIMIT ?", (from_ts, to_ts, limit))
    return [dict(r) for r in rows]


def update_event(event_id: str, **fields) -> bool:
    if not fields:
        return False
    allowed = {"title", "start", "end", "location", "notes", "status", "attendees"}
    sets, params = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        sets.append(f"{k}=?")
        params.append(_dump(v) if isinstance(v, (list, dict)) else v)
    if not sets:
        return False
    params.append(event_id)
    db().update(f"UPDATE comm_events SET {', '.join(sets)} WHERE event_id=?", tuple(params))
    return True


def cancel_event(event_id: str) -> bool:
    return update_event(event_id, status="cancelled")


def conflicts(start: float, end: float) -> list:
    rows = db().query(
        "SELECT * FROM comm_events WHERE status!='cancelled' AND start < ? AND end > ?",
        (float(end), float(start)))
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# send ledger (rate limiting / duplicates / cooldowns / audit trail ids)
# ---------------------------------------------------------------------------

def log_send(platform: str, recipient: str, content_hash: str,
             draft_id: str = "", result: str = "") -> None:
    db().update(
        "INSERT INTO comm_send_log(ts,platform,recipient,content_hash,draft_id,result) "
        "VALUES(?,?,?,?,?,?)",
        (time.time(), platform, recipient, content_hash, draft_id, result))


def sends_since(platform: str, since_ts: float) -> list:
    return [dict(r) for r in db().query(
        "SELECT * FROM comm_send_log WHERE platform=? AND ts>=?", (platform, since_ts))]


def sends_to_since(recipient: str, since_ts: float) -> list:
    return [dict(r) for r in db().query(
        "SELECT * FROM comm_send_log WHERE recipient=? AND ts>=?", (recipient, since_ts))]


# ---------------------------------------------------------------------------
# policy overrides + workflows
# ---------------------------------------------------------------------------

def set_policy_level(scope: str, level: int) -> None:
    db().update("INSERT OR REPLACE INTO comm_policy(scope,level,updated_at) VALUES(?,?,?)",
                (scope, int(level), time.time()))


def get_policy_level(scope: str) -> int | None:
    rows = db().query("SELECT level FROM comm_policy WHERE scope=?", (scope,))
    return int(rows[0]["level"]) if rows else None


def drop_policy(scope: str) -> None:
    db().update("DELETE FROM comm_policy WHERE scope=?", (scope,))


def save_workflow(workflow_id: str, name: str, definition: dict, enabled: bool = True) -> None:
    db().update(
        "INSERT OR REPLACE INTO comm_workflows(workflow_id,name,definition,enabled,created_at) "
        "VALUES(?,?,?,?,?)",
        (workflow_id, name, _dump(definition), 1 if enabled else 0, time.time()))


def list_workflows(enabled_only: bool = False) -> list:
    rows = db().query("SELECT * FROM comm_workflows" +
                      (" WHERE enabled=1" if enabled_only else ""))
    out = []
    for r in rows:
        d = dict(r)
        d["definition"] = _load(d.get("definition"), {})
        out.append(d)
    return out


def record_run(workflow_id: str, run_id: str, trigger_summary: str, steps: list,
               success: bool, started: float, error: str = "") -> None:
    db().update(
        "INSERT OR REPLACE INTO comm_workflow_runs(run_id,workflow_id,trigger_summary,"
        "steps,success,started,finished,error) VALUES(?,?,?,?,?,?,?,?)",
        (run_id, workflow_id, trigger_summary[:200], _dump(steps),
         1 if success else 0, started, time.time(), error[:200]))


def recent_runs(workflow_id: str = "", limit: int = 20) -> list:
    if workflow_id:
        rows = db().query(
            "SELECT * FROM comm_workflow_runs WHERE workflow_id=? ORDER BY started DESC LIMIT ?",
            (workflow_id, limit))
    else:
        rows = db().query("SELECT * FROM comm_workflow_runs ORDER BY started DESC LIMIT ?",
                          (limit,))
    out = []
    for r in rows:
        d = dict(r)
        d["steps"] = _load(d.get("steps"), [])
        out.append(d)
    return out
