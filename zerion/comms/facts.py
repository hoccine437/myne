# comms/facts.py
"""Factual integrity gate for outbound candidates.

A Zerion-authored reply must not assert facts/commitments the store cannot
back. This module checks the CANDIDATE (never the incoming message) against
existing evidence:

  * commitment shapes ("I'll bring the money tomorrow", "meeting confirmed",
    "price is 500") must be grounded in memory/context or the candidate is
    downgraded to ASK
  * factual claims about the user's world must not contradict Verifier-known
    states (UNCERTAIN evidence stays marked; never upgraded)

Grounding sources: long-term memory (identity/preferences), knowledge DB
(capability/workflow patterns, verified/supported records), conversation
history. Unknown is UNKNOWN — never translated into fact downstream.
"""

from __future__ import annotations

import re

_COMMITMENT_RE = re.compile(
    r"\b(i('ll| will) (pay|send|bring|deliver|sign|commit|guarantee|promise)|"
    r"i promise|guaranteed|confirmed for|book(ed)? it|price is \$?\d|"
    r"the meeting is (confirmed|set) (for|at)\b)", re.I)
_CLAIM_RE = re.compile(r"\b.the (price|date|time|address|number|code) (is|was)\b",
                       re.I)
_DATE_NUM_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\$\s?\d+|\d+\s?(usd|eur|dzd))\b", re.I)


def commitment_atoms(text: str) -> list:
    return [m.group(0) for m in _COMMITMENT_RE.finditer(text or "")]


def grounded_evidence(query: str, limit: int = 6) -> dict:
    """What the knowledge base can support about query, in truth terms."""
    try:
        from knowledge.manager import KnowledgeManager
        km = KnowledgeManager()
        rows = km.searcher.search(query, limit)
    except Exception:
        rows = []
    states = {"verified": 0, "supported": 0, "uncertain": 0,
              "contradicted": 0, "unknown": 0, "records": len(rows)}
    for r in rows:
        meta = r.get("metadata") or {}
        state = str(meta.get("verification_status", "unknown"))
        states[state if state in states else "unknown"] += 1
    return states


def candidate_grounding(candidate: str, context_text: str = "") -> dict:
    """Classify factual risk of an OUTBOUND candidate."""
    commitments = commitment_atoms(candidate)
    numbers = _DATE_NUM_RE.findall(candidate or "")
    supported = {}
    for atom in commitments + numbers:
        ev = grounded_evidence(str(atom)[:120], 3)
        in_context = str(atom).lower() in (context_text or "").lower()
        supported[str(atom)[:60]] = bool(ev["verified"] or ev["supported"] or in_context)
    return {
        "commitments": commitments,
        "hard_facts": numbers,
        "grounding": supported,
        "unverified_ids": [k for k, v in supported.items() if not v],
        "clean": not (commitments or numbers) or
                (not [k for k, v in supported.items() if not v]),
    }
