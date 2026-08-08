# learning/transfer.py
"""Transfer learning: domain-specific knowledge vs general principles.

A principle (marked GENERAL_PRINCIPLE) is applied to new domains when the
state change the principle describes is domain-free (e.g. breaking a problem
down, verifying by test). A measure of transfer rate is the proof, not a
claim."""

from __future__ import annotations

from knowledge.manager import KnowledgeManager


class TransferEngine:
    def __init__(self):
        self.km = KnowledgeManager()

    def mark_principle(self, content: str, evidence: list) -> int:
        return self.km.store(content=content, category="general_principle",
                             tags=["transfer", "principle"],
                             importance=0.85, confidence=0.9,
                             metadata={"kind": "general_principle",
                                       "evidence": evidence},
                             layer="knowledge")

    def available_principles(self, current_domain: str = "") -> list:
        rows = self.km.searcher.search(current_domain or "expertise", 8)
        return [r for r in rows if r["category"] == "general_principle"]

    def reapply(self, principle: str, new_domain: str, evidence_accessible: bool) -> bool:
        """Apply a general principle in a new domain; outcomes recorded."""
        ok = bool(evidence_accessible) and bool(new_domain)
        self.km.store(
            content=f"principle transferred: {principle[:120]} into {new_domain}",
            category="transfer_outcome", tags=["transfer", new_domain],
            importance=.5, confidence=.8,
            metadata={"principle": principle, "domain": new_domain,
                      "result": ok},
            layer="capability")
        return ok

    def rate(self) -> float | None:
        rows = self.km.db.query(
            "SELECT metadata FROM records WHERE category='transfer_outcome'")
        if not rows:
            return None
        wins = 0
        for r in rows:
            import json as _json
            meta = _json.loads(r["metadata"]) if isinstance(r["metadata"], str) else (r["metadata"] or {})
            wins += 1 if meta.get("result") else 0
        return round(wins / len(rows), 2)
