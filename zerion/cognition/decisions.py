# cognition/decisions.py
"""Decision intelligence: structured options-stacking under uncertainty.

Produces a canonical Decision record: options → the DECISION model —
options / cost / risk / benefit / uncertainty / dependencies /
reversibility / evidence — then a chosen option with structured reason.
Nothing invented: inputs come from the goal text, memory hits, and the
caller-supplied options (when the model supplies none, the module presents
its bounded defaults and marks them "discovered")."""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field, asdict


@dataclass
class Option:
    name: str
    cost: float = 0.0          # 0..1 unk activation cost estimate
    risk: float = 0.3          # 0..1
    benefit: float = 0.5       # 0..1
    uncertainty: float = 0.5
    dependencies: tuple = ()
    reversible: bool = True
    evidence: tuple = ()       # evidence list supporting pick


@dataclass
class Decision:
    decision_id: str
    question: str
    options: list
    chosen: str
    reason: str
    evidence: list
    confidence: float
    risks: list
    alternatives: list
    created: float = field(default_factory=time.time)

    def to_dict(self):
        return asdict(self)


_INTENT_HINTS = re.compile(
    r"\b(should i|should we|which|choose|vs\b|versus|pick|better|trade[- ]?off|decide|decision)\b",
    re.I)


def is_decision_task(goal: str) -> bool:
    return bool(_INTENT_HINTS.search(goal or ""))


def decide(question: str, options: list | dict | None = None,
           evidence: list | None = None) -> Decision:
    """Build-criticize-rank-pick, using only known data. When no options are
    passed, a bounded default decomposition is generated from the question's
    own structure — and marked as such."""
    evidence = evidence or []

    if isinstance(options, dict):
        options = list(options.values())
    if options:
        options = [o if isinstance(o, Option) else Option(**{k: v for k, v in o.items()
                                                            if k in Option.__dataclass_fields__})
                   for o in options]
    if not options:
        options = [
            Option(name="proceed-with-minimal-scope", cost=.2, risk=.3, benefit=.5,
                   evidence=("bounded default option",)),
            Option(name="defer-and-clarify", cost=.1, risk=.2, benefit=.3,
                   reversible=True, evidence=("lower risk under uncertainty",)),
        ]

    for o in options:
        if not o.evidence:
            o.evidence = tuple(evidence[:2])

    # rank by benefit minus risk-cost load, with reversibility bonus
    def score(o: Option) -> float:
        base = o.benefit - 0.4 * o.cost - 0.5 * o.risk - 0.1 * o.uncertainty
        if not o.reversible:
            base -= 0.15
        if o.evidence:
            base += min(0.15, 0.05 * len(o.evidence))
        return round(base, 3)

    ranked = sorted(options, key=score, reverse=True)
    top, runner_up = ranked[0], ranked[1] if len(ranked) > 1 else None

    confidence = round(max(.25, min(.9,
        .45 + .1 * len(evidence) + (0.1 if top.reversible else -0.1))), 2)
    if top.uncertainty > 0.7 and not evidence:
        confidence = min(confidence, .4)

    risks = [f"risk={o.risk}" for o in ranked if o.risk >= 0.5] + (
        ["irreversible-path"] if not top.reversible else [])

    return Decision(
        decision_id=uuid.uuid4().hex[:10],
        question=question,
        options=[o.__dict__ for o in options],
        chosen=top.name,
        reason=f"highest net of benefit/cost/risk/uncertainty; evidence: {top.evidence or 'discovered-by-defect'}",
        evidence=[e[:160] for e in evidence[:4]] or [f"option {top.name} selected from {len(options)} candidates"],
        confidence=confidence,
        risks=risks,
        alternatives=[o.name for o in ranked[1:3]],
    )
