# learning/verification.py
"""Truth Engine: nothing becomes knowledge until evidence earns it.

Promotion states: VERIFIED / SUPPORTED / UNCERTAIN / CONTRADICTED / REJECTED
Rule: a single source never promotes to VERIFIED for factual knowledge;
executable proof (tests) can. Everything writes an audit note back onto the
record's metadata so learning remains auditable."""

from __future__ import annotations

from knowledge.manager import KnowledgeManager

STATES = ("rejected", "uncertain", "supported", "verified", "contradicted")

_STATE_VALUE = {"uncertain": .3, "supported": .55, "verified": .95,
                "contradicted": .05, "rejected": .0}


class TruthEngine:
    def __init__(self):
        self.km = KnowledgeManager()

    def evaluate(self, record_id: int, evidence: list, executable_proof: bool = False) -> dict:
        """Multi evidence rule:
        • executable proof (tests passed) → VERIFIED
        • ≥2 independent supporting sources → SUPPORTED
        • contradictory evidence → CONTRADICTED (demotes)
        • no evidence → UNCERTAIN
        Nothing invents proof: input evidence is passed in, not assumed."""
        hits = self.km.db.query("SELECT metadata, confidence FROM records WHERE id=?", (record_id,))
        if not hits:
            return {"state": "unknown-record", "record_id": record_id}

        meta = self.km.db.query("SELECT metadata FROM records WHERE id=?", (record_id,))[0]["metadata"]
        import json as _json

        if executable_proof:
            state = "verified"
            confidence = 0.95
        else:
            support = [e for e in evidence if str(e).lower() in ("support", True, "consistent")]
            conflict = [e for e in evidence if str(e).lower() in ("contradict", "conflict")]
            if conflict:
                state = "contradicted"
                confidence = 0.08
            elif len(support) >= 2:
                state = "supported"
                confidence = 0.65
            elif evidence:
                state = "uncertain"
                confidence = 0.45
            else:
                state = "uncertain"
                confidence = 0.25

        base = _json.loads(meta) if isinstance(meta, str) else (meta or {})
        base["verification_status"] = state
        base.setdefault("evidence_history", []).append(
            {"evidence": evidence[:8], "state": state, "at": time_stamp()})
        self.km.db.update(
            "UPDATE records SET metadata=?, confidence=? WHERE id=?",
            (_json.dumps(base), confidence, record_id))
        return {"record_id": record_id, "state": state, "confidence": confidence}


def time_stamp() -> float:
    import time
    return round(time.time(), 3)
