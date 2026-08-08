# learning/meta.py
"""Meta-learning: learn how Zerion learns.

Records learning-strategy outcomes; picks the best by MEASURED retention
(score + review pass rate), not intuition. What I learn / what I lack /
best source / test myself with — answers come from the knowledge graph and
the progress model only."""

from __future__ import annotations

import time

from knowledge.manager import KnowledgeManager


class MetaLearner:
    def __init__(self):
        self.km = KnowledgeManager()

    # ---- signals ---------------------------------------------------------

    def note_strategy(self, strategy: str, elapsed_s: float,
                       retention_passes: int, retention_fails: int) -> int:
        return self.km.store(
            content=f"learning strategy {strategy}: {elapsed_s:.1f}s, retention {retention_passes}/{retention_fails}",
            category="learning_strategy", tags=[strategy],
            importance=.5, confidence=.9,
            metadata={"strategy": strategy, "elapsed_s": elapsed_s,
                      "retention_passes": retention_passes,
                      "retention_fails": retention_fails, "ts": time.time()},
            layer="learning_strategy")

    def best_strategy(self, top: int = 1) -> list:
        """Measured leader ranking (accuracy-dominated; speed breaks ties)."""
        rows = self.km.db.query(
            "SELECT metadata FROM records WHERE category='learning_strategy'")
        stats = {}
        import json as _json
        for r in rows:
            meta = _json.loads(r["metadata"]) if isinstance(r["metadata"], str) else (r["metadata"] or {})
            s = meta.get("strategy")
            if not s:
                continue
            passes = int(meta.get("retention_passes", 0))
            fails = int(meta.get("retention_fails", 0))
            elapsed = float(meta.get("elapsed_s", 0))
            acc = passes / max(1, passes + fails)
            cur = stats.get(s)
            stats[s] = (acc + (cur[0] if cur else 0),
                        elapsed + (cur[1] if cur else 0),
                        (cur[2] if cur else 0) + 1)
        ranked = sorted(stats.items(), key=lambda kv: (-(kv[1][0]/max(1, kv[1][2])), kv[1][1]))
        return [{"strategy": name, "mean_retention": round(acc / max(1, n), 2)}
                for name, (acc, _e, n) in ranked[:top]]

    # ---- self-questions the loop needs ------------------------------------

    def answer(self, question: str, progress=None, retention=None) -> str:
        q = question.lower()
        if "what am i missing" in q or "gap" in q:
            if progress is not None:
                unknown = progress.unknown_concepts
                return "missing: " + (", ".join(unknown) if unknown else "nothing")
        if "should i practice" in q or "retention" in q:
            due = retention.due() if retention else []
            return f"{len(due)} item(s) due for review." if due else "nothing due right now."
        if "which strategy" in q or "best strategy" in q:
            best = self.best_strategy(1)
            return (f"{best[0]['strategy']} (measured retention {best[0]['mean_retention']})"
                    if best else "no strategy measured yet")
        return ""
