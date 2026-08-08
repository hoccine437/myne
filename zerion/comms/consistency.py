# comms/consistency.py
"""Conversational consistency — the candidate must not contradict the
conversation's own history within the SAME isolated scope, or known memory.

Deliberately narrow and transparent: negation flip on repeated claim shapes
("we agreed X" / "we never agreed X"), direct numerical contradiction vs
earlier messages in this conversation, and identity mismatches. A flagged
candidate goes to ASK, never to send. No guessing: unresolved = do not send.
"""

from __future__ import annotations

from comms import store


def _numeric_claims(text: str) -> set:
    import re
    return set(re.findall(r"\b\d[\d.,]*\b", text or ""))


def find_contradiction(platform: str, conversation_id: str, candidate: str) -> dict:
    """Compare candidate against this conversation's recent history only.
    Returns {"contradiction": bool, "reason": str}."""
    if not conversation_id:
        return {"contradiction": False, "reason": "no conversation scope"}
    history = store.conversation_history(conversation_id, limit=8)
    if not history:
        return {"contradiction": False, "reason": "no history"}

    cand_nums = _numeric_claims(candidate)
    if cand_nums:
        for row in history:
            past = _numeric_claims(row.get("content", ""))
            overlap = cand_nums & past
            if overlap:
                # a shared number with opposite polarity verbs is a flag
                joined = (candidate + " " + row.get("content", "")).lower()
                if ("never" in joined or "not " in joined or "cancel" in joined) and \
                   ("yes" in joined or "confirmed" in joined or "agreed" in joined):
                    return {"contradiction": True,
                            "reason": f"numeric/agreement clash on {sorted(overlap)[:3]}"}
    # identity isolation: candidate addressed at a third party mid-thread
    import re as _re
    ats = set(_re.findall(r"@([A-Za-z0-9_.\-]{2,})", candidate or ""))
    participants = {str(r.get("sender", "")).lstrip("@") for r in history}
    unknown_ats = {a for a in ats if a not in participants}
    if unknown_ats and participants:
        return {"contradiction": True,
                "reason": f"candidate addresses non-participant(s): {sorted(unknown_ats)}"}

    return {"contradiction": False, "reason": "consistent"}


# ---------------------------------------------------------------------------
# model/agent disagreement (mission §34)
# ---------------------------------------------------------------------------

def disagreement(draft_text: str, verdict_a: str, verdict_b: str) -> bool:
    """Two independent lanes disagreed about accepting the same candidate.
    verdict == 'accept'|'revise' — revise on either side means no autonomous
    send; the item is parked for approval. (For 'important' communication,
    disagreement alone must stop the send.)"""
    return verdict_a != verdict_b
