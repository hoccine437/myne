# learning/errors.py
"""Error Memory: failures are knowledge too — structured as
problem → attempt → failure → cause → correction → solved solution — so the
same mistake never happens twice (records are searchable through the
canonical knowledge base)."""

from __future__ import annotations

import time

from knowledge.manager import KnowledgeManager

CAUSES = ("assumption", "boundary", "ordering", "arithmetic", "format",
          "timing", "permission", "unknown")


class ErrorMemory:
    def __init__(self):
        self.km = KnowledgeManager()

    def record(self, problem: str, attempt: str, failure: str, cause: str,
               correction: str, solution: str) -> int:
        """Record a structured failure (never silent, never blind).
        All fields coerce to str: callers pass numbers (expected values)
        and exceptions as often as prose."""
        problem, attempt = str(problem), str(attempt)
        failure, cause = str(failure), str(cause)
        correction, solution = str(correction), str(solution)
        content = (f"PROBLEM: {problem[:160]}\nATTEMPT: {attempt[:200]}\n"
                   f"FAILURE: {failure[:200]}\nCAUSE: {cause}\n"
                   f"CORRECTION: {correction[:200]}\nSOLUTION: {solution[:200]}")
        return self.km.store(content=content, category="error_memory",
                             tags=[cause, "failure", "learning"],
                             importance=0.7, confidence=0.8,
                             metadata={
                                 "problem": problem, "attempt": attempt,
                                 "failure": failure, "cause": cause,
                                 "correction": correction,
                                 "solution": solution,
                                 "ts": time.time(),
                             }, layer="capability")

    def retrieve_similar(self, problem: str, limit: int = 5) -> list:
        # search-then-filter must happen on a WIDE window: ranking by
        # importance/confidence can crowd error rows out of a small top-k,
        # which would silently erase exactly the failures meant to be found.
        found = self.km.searcher.search(problem, max(limit * 8, 30))
        out = []
        for r in found:
            if r["category"] != "error_memory":
                continue
            out.append({"cause": r["metadata"].get("cause"),
                        "correction": r["metadata"].get("correction"),
                        "solution": r["metadata"].get("solution")})
        return out[:limit]
