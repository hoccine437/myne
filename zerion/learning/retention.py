# learning/retention.py
"""Spaced recall / retention.

Per-record adaptive schedule: pass → interval doubles; fail → interval
halves (bounded). Due items drive targeted review surfaces. Facts are
re-probed, never just re-read."""

from __future__ import annotations

import time

from knowledge.manager import KnowledgeManager

_MIN_DAYS = 1.0
_MAX_DAYS = 90.0


class RetentionScheduler:
    def __init__(self):
        self.km = KnowledgeManager()

    def _interval(self, record: dict) -> float:
        meta = record.get("metadata") or {}
        base = float(meta.get("review_interval_days", _MIN_DAYS))
        return max(_MIN_DAYS, min(_MAX_DAYS, base))

    def note_pass(self, record_id: int) -> None:
        rows = self.km.db.query("SELECT metadata FROM records WHERE id=?", (record_id,))
        if not rows:
            return
        import json as _json
        meta = _json.loads(rows[0]["metadata"]) if isinstance(rows[0]["metadata"], str) else (rows[0]["metadata"] or {})
        days = min(_MAX_DAYS, self._interval(rows[0] | {"metadata": meta}) * 2)
        meta["review_interval_days"] = days
        meta["next_review_at"] = time.time() + days * 86400
        meta["review_passes"] = int(meta.get("review_passes", 0)) + 1
        self.km.db.update("UPDATE records SET metadata=? WHERE id=?", (_json.dumps(meta), record_id))

    def note_fail(self, record_id: int) -> None:
        rows = self.km.db.query("SELECT metadata FROM records WHERE id=?", (record_id,))
        if not rows:
            return
        import json as _json
        meta = _json.loads(rows[0]["metadata"]) if isinstance(rows[0]["metadata"], str) else (rows[0]["metadata"] or {})
        days = max(_MIN_DAYS, self._interval(rows[0] | {"metadata": meta}) / 2)
        meta["review_interval_days"] = days
        meta["next_review_at"] = time.time() + days * 86400
        meta["review_fails"] = int(meta.get("review_fails", 0)) + 1
        self.km.db.update("UPDATE records SET metadata=? WHERE id=?", (_json.dumps(meta), record_id))

    def due(self, limit: int = 20) -> list:
        now = time.time()
        rows = self.km.db.query(
            "SELECT id, content, metadata FROM records WHERE metadata LIKE ?", ("%next_review_at%",))
        due = []
        import json as _json
        for r in rows:
            meta = _json.loads(r["metadata"]) if isinstance(r["metadata"], str) else (r["metadata"] or {})
            if meta.get("next_review_at", 0) <= now:
                due.append({"id": r["id"], "content": r["content"][:120],
                            "interval_days": meta.get("review_interval_days", _MIN_DAYS)})
        return due[:limit]
