# meta.py
"""Meta-intelligence: Zerion's honest self-knowledge.

Answers from live state only — no invented capabilities. The canonical
soul-answer path: intent/fast_planner routes these questions here before
paying for an LLM call."""

from __future__ import annotations

import os
import time


def _knowledge_stats():
    try:
        from knowledge.manager import KnowledgeManager
        rows = KnowledgeManager().db.query(
            "SELECT layer, COUNT(*) AS n, AVG(confidence) AS c, AVG(importance) AS i "
            "FROM records GROUP BY layer")
        return [(r["layer"], r["n"], round(r["c"] or 0, 2), round(r["i"] or 0, 2)) for r in rows]
    except Exception:
        return []


def answer(question: str) -> str | None:
    """The fast_planner probes this. Returns None when the question isn't
    really a "what do you know/can you do" so the caller falls through."""
    q = (question or "").lower().strip()
    asked = any(k in q for k in (
        "what do you know", "what don't you know", "what do you not know",
        "what are you", "what can you do", "your capabilities",
        "are you able", "can you do", "can you help",
        "what are your capabilities",
        "what can't you do", "what can't you handle", "what can't you control",
        "who are your agents", "what agents do you have",
    ))
    if not asked:
        return None

    lines = []
    rows = _knowledge_stats()
    total = sum(r[1] for r in rows)
    if total:
        lines.append(f"I hold {total} structured record(s) across: "
                     + ", ".join(f"{l}×{n}" for l, n, _, _ in rows[:6]))
    else:
        lines.append("No memory records yet — ask me something and give me context to learn from.")

    try:
        from tools.manager import tool_manager
        tools = tool_manager.list_tools()
        lines.append(f"{len(tools)} executable tool(s) currently registered (" +
                     ", ".join(t["name"] for t in tools[:8]) + "…)")
    except Exception:
        pass

    try:
        from agents.types import AGENT_TYPES
        lines.append(f"{len(AGENT_TYPES)} agent types ready for delegation: " +
                     ", ".join(sorted(AGENT_TYPES)) + ".")
    except Exception:
        pass

    try:
        from phone.device import probe_device
        d = probe_device()
        kind = "Android/Termux" if d["is_termux"] else d["os"]
        lines.append(f"Device: {kind} ({d['arch']}), screen "
                     f"{d['screen'] or 'unknown'}, battery "
                     f"{(d['battery'] or {}).get('percent', '?')}%.")
    except Exception:
        pass

    q2 = q.lower()
    if any(k in q2 for k in ("can't", "can not", "cannot", "unable")):
        try:
            from phone.device import probe_device
            d = probe_device()
            missing = [k for k, v in d["io"].items() if v is False]
            if missing:
                lines.append("Unavailable here: " + ", ".join(missing) + ".")
        except Exception:
            pass
        lines.append("I cannot act unapproved: every consequential action "
                     "pauses for your confirmation by Constitution policy.")
    return "\n".join(lines) or None
