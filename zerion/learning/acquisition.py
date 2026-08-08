# learning/acquisition.py
"""Knowledge Acquisition: classify every acquired fragment as one of
SOURCE / CLAIM / FACT / INTERPRETATION / HYPOTHESIS / UNKNOWN, and store
them with full metadata — because Zerion must never treat "a document
said so" as truth.

Sources may be: document, web, file, video, image, audio, dataset, code,
experiment, user, experience, agent, local database. Every one of those
returns a knowledge record with evidence kind, provenance, and the
classification label; nothing is promoted to FACT until the truth engine
touches it."""

from __future__ import annotations

import time
from dataclasses import dataclass

from knowledge.manager import KnowledgeManager


@dataclass
class Fragment:
    kind: str          # source | claim | fact | interpretation | hypothesis | unknown
    content: str
    source: str        # web/file/experiment/user/…
    recorded_at: float = 0.0

    def __post_init__(self):
        self.recorded_at = self.recorded_at or time.time()


_KIND_MARKERS = {
    "unknown": ("nothing observed", "unclear", "missing", "unverified", "no data"),
    "fact": ("measured", "observed", "verified", "evidence", "benchmark", "test passes"),
    "claim": ("claims", "said", "allegedly", "according to", "the report says"),
    "hypothesis": ("hypothesizes", "probably", "maybe", "might", "suggests", "then"),
    "interpretation": ("interpretation", "seems", "implies", "we infer", "suggests that"),
}


class AcquisitionLayer:
    def classify(self, content: str, source: str = "user") -> Fragment:
        text = content.lower()
        # precedence matters: exclusive unknown markers first ("nothing
        # observed" contains "observed" — a fact marker would misfire)
        for kind in ("unknown", "fact", "claim", "hypothesis", "interpretation"):
            if any(m in text for m in _KIND_MARKERS[kind]):
                return Fragment(kind=kind, content=content, source=source)
        return Fragment(kind="claim", content=content, source=source)

    def acquire(self, content: str, source: str = "user", importance: float = 0.45,
                confidence: float = 0.3, domain: str = "general") -> int:
        frag = self.classify(content, source)
        meta = {
            "fragment_kind": frag.kind,
            "source_kind": frag.source,
            "recorded_at": frag.recorded_at,
            # IMPORTANT: nothing we acquire is "verified" on arrival; the
            # truth engine promotes it separately
            "verification_status": "unverified",
            "domain": domain,
        }
        record_id = KnowledgeManager().store(
            content=frag.content, category=f"frag:{frag.kind}",
            tags=[frag.kind, frag.source, domain], importance=importance,
            confidence=confidence, metadata=meta, layer="knowledge")
        # relationship graph: every fragment joins the domain it belongs to
        # (existing intelligence/world graph_edges table — no second store).
        if record_id:
            try:
                from intelligence.world import WorldModel
                WorldModel().link(f"record:{record_id}", "part_of", f"domain:{domain}", .6)
            except Exception:
                pass  # the graph is an index, never a reason acquisition fails
        return record_id
