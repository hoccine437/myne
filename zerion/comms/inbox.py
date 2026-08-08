# comms/inbox.py
"""Unified inbox — intake + logical views over the normalized store.

Intake: one path for every inbound item regardless of platform:
  poll/connector → UnifiedMessage → classify → risk markers → store
  → contact context touch → decide notify-worthy (urgent/high only,
  spam/low never pings the user).

Views: search / filter / prioritize / group by person / task / platform —
pure SQL over comm_messages; the original platform is preserved on every row.
"""

from __future__ import annotations

from comms import store
from comms.classify import classify_message, risk_markers, contains_task

_URGENCY_RANK = {"urgent": 0, "high": 1, "normal": 2, "low": 3}


def ingest(msg) -> dict:
    """The single intake. Returns {stored, stable_id, classification}."""
    classify_message(msg)
    row_id = store.store_message(msg)
    if row_id and msg.sender:
        try:
            store.contact_note(msg.sender, (msg.reply_context or msg.content)[:80])
        except Exception:
            pass
    return {"stored": bool(row_id), "stable_id": msg.stable_id(),
            "classification": msg.classification, "urgency": msg.urgency,
            "duplicate": not row_id}


def notify_worthy(msg) -> bool:
    """Only genuinely attention-worthy items may interrupt the user."""
    return msg.urgency in ("urgent",) or (
        msg.urgency == "high" and msg.classification not in ("spam", "low"))


def overview() -> dict:
    rows = store.query_messages(limit=500)
    by_platform = {}
    for r in rows:
        by_platform[r["platform"]] = by_platform.get(r["platform"], 0) + 1
    return {"total": len(rows), "by_platform": by_platform,
            "pending_drafts": len(store.pending_drafts()),
            "unclassified": sum(1 for r in rows if not r["classification"]),
            "urgent": sum(1 for r in rows if r["urgency"] == "urgent")}


def search(query: str, platform: str = "", limit: int = 50) -> list:
    rows = store.query_messages(limit=500)
    q = (query or "").lower()
    out = []
    for r in rows:
        if platform and r["platform"] != platform:
            continue
        if q and q not in (r["content"] + " " + r["sender"] +
                          " " + r["reply_context"]).lower():
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out


def prioritized(platform: str = "", limit: int = 50) -> list:
    rows = search("", platform=platform, limit=500)
    rows.sort(key=lambda r: (_URGENCY_RANK.get(r["urgency"], 3), -r["timestamp"]))
    return rows[:limit]


def group_by_person(limit: int = 200) -> dict:
    groups = {}
    for r in store.query_messages(limit=limit):
        groups.setdefault(r["sender"] or "(unknown)", []).append(r)
    return groups


def group_by_task(limit: int = 200) -> dict:
    rows = store.query_messages(limit=limit)
    return {"has_task": [r for r in rows if contains_task(r["content"])],
            "informational": [r for r in rows if not contains_task(r["content"])]}


def summarize(platform: str = "", limit: int = 25) -> str:
    rows = prioritized(platform=platform, limit=limit)
    if not rows:
        return "Inbox is empty."
    lines = []
    for r in rows:
        mark = {"urgent": "!!", "high": "!", "normal": "-", "low": "."}[r["urgency"]]
        lines.append(f"{mark} [{r['platform']}] {r['sender']}: {r['content'][:80] or r['reply_context'][:80]}")
    counts = overview()
    head = (f"{counts['total']} message(s) — "
            + ", ".join(f"{p}×{n}" for p, n in sorted(counts["by_platform"].items())))
    return head + "\n" + "\n".join(lines)
