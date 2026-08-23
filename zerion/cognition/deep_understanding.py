"""Operational Deep Understanding contract for Zerion.

The names in this module are not claims of consciousness or human emotion.
They are 19 observable behaviours that the turn pipeline asks the model and
local engines to perform, with explicit evidence and safety boundaries. A
capability is only reported as wired when it has a real runtime hook; live
provider quality and physical-device effects remain externally verifiable.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class UnderstandingCapability:
    number: int
    name: str
    instruction: str
    evidence: str
    status: str  # WIRED | PARTIAL | OWNER-GATED


_CAPABILITY_ROWS = (
    ("Independent Thinking", "generate at least one alternative before choosing when the request is non-trivial", "reasoning alternatives + revisable hypotheses", "WIRED"),
    ("Decision Making", "compare options by benefit, cost, risk, uncertainty, dependencies, and reversibility", "cognition.decisions Decision record", "WIRED"),
    ("Priority Management", "rank the user's goal, urgency, safety, and dependencies before spending effort", "local urgency/goal signals + planner ordering", "WIRED"),
    ("Critical Thinking", "challenge assumptions, contradictions, unsupported claims, and missing evidence", "Self-Critic + evidence rules", "WIRED"),
    ("Predictive Reasoning", "state likely outcomes, leading indicators, and confidence without presenting forecasts as facts", "model-guided forecast protocol; no live forecast guarantee", "PARTIAL"),
    ("Adaptability", "change reasoning mode and plan when new evidence, feedback, or constraints arrive", "cognition modes + resumable planner + workspace adaptation", "WIRED"),
    ("Continuous Learning", "retain validated outcomes and improve future method selection without silently changing law", "learning engine + capability experience records", "WIRED"),
    ("Contextual Memory", "use relevant history and durable memory while treating uncertain memory as uncertain", "SessionMemory + memory/knowledge context assembly", "WIRED"),
    ("Emotional Intelligence", "detect language-level tone and urgency, respond respectfully, and never claim human feelings", "bounded tone/urgency signal; not clinical emotion inference", "PARTIAL"),
    ("Realism", "separate fact, inference, proposal, and unknown; require tools for fresh external claims", "evidence-gated tools and response protocol", "WIRED"),
    ("Intellectual Courage", "say when evidence is insufficient, correct an earlier answer, and refuse unsafe certainty", "uncertainty and correction rules", "WIRED"),
    ("Problem Solving", "define the goal, decompose dependencies, choose tools, execute, and verify", "planner → Tool Manager → verifier", "WIRED"),
    ("Creativity", "offer multiple useful novel approaches when appropriate and label proposals as proposals", "bounded alternative-generation instruction", "PARTIAL"),
    ("Autonomy", "act through registered tools and agents only within permissions, approvals, and explicit scope", "Agent Engine + Tool Manager + Constitution", "OWNER-GATED"),
    ("Self-Verification", "check output against expected evidence before reporting completion", "planner expected_result + Self-Critic", "WIRED"),
    ("Failure Learning", "record failures, cause signals, and corrective lessons; do not turn failure into success", "learning/errors.py + capability experience", "WIRED"),
    ("Interest Protection", "protect the user's privacy, safety, resources, intent, and reversibility over convenience", "Constitution + approval gates + secret scrubbing", "WIRED"),
    ("Principle Formation", "propose a candidate preference from explicit repeated feedback; never rewrite Constitution automatically", "owner-approved memory/protected-law boundary", "OWNER-GATED"),
    ("Self-Evolution", "identify a gap and stage a tested, reviewable upgrade; never deploy protected changes autonomously", "evolution manifests + protected-core lock", "OWNER-GATED"),
)

CAPABILITY_COUNT = len(_CAPABILITY_ROWS)
CAPABILITY_NAMES = tuple(row[0] for row in _CAPABILITY_ROWS)


@dataclass(frozen=True)
class DeepUnderstandingProfile:
    capabilities: tuple[UnderstandingCapability, ...]
    tone: str
    urgency: str
    decision_signal: bool
    complexity_signal: bool

    @property
    def wired_count(self) -> int:
        return sum(c.status == "WIRED" for c in self.capabilities)

    @property
    def prompt_block(self) -> str:
        lines = [
            "DEEP UNDERSTANDING CONTRACT: apply these 19 observable behaviours "
            "to this turn. Do not claim consciousness, feelings, certainty, "
            "or completed external actions without evidence.",
            f"Local language signals only: tone={self.tone}; urgency={self.urgency}; "
            f"decision={str(self.decision_signal).lower()}; "
            f"complexity={str(self.complexity_signal).lower()}.",
        ]
        lines.extend(
            f"{cap.number}. {cap.name}: {cap.instruction}."
            for cap in self.capabilities
        )
        return "\n".join(lines)

    def telemetry(self) -> dict:
        return {
            "capabilities": len(self.capabilities),
            "wired": self.wired_count,
            "partial": sum(c.status == "PARTIAL" for c in self.capabilities),
            "owner_gated": sum(c.status == "OWNER-GATED" for c in self.capabilities),
            "tone": self.tone,
            "urgency": self.urgency,
            "decision": self.decision_signal,
            "complexity": self.complexity_signal,
        }

    def matrix(self) -> list[dict]:
        """Safe report data; contains no user text or secrets."""
        return [
            {"number": c.number, "name": c.name, "status": c.status,
             "evidence": c.evidence}
            for c in self.capabilities
        ]


def _language_signals(text: str) -> tuple[str, str, bool, bool]:
    lowered = (text or "").lower()
    if any(word in lowered for word in ("panic", "emergency", "urgent", "asap", "immediately")):
        urgency = "high"
    elif any(word in lowered for word in ("soon", "today", "deadline", "important")):
        urgency = "medium"
    else:
        urgency = "normal"

    if any(word in lowered for word in ("please", "thanks", "thank you", "worried", "sad", "angry")):
        tone = "emotionally-marked"
    elif "?" in lowered:
        tone = "questioning"
    else:
        tone = "neutral-or-unknown"

    decision = bool(re.search(r"\b(should|choose|which|better|compare|options?|versus|vs|decide|decision)\b", lowered))
    complexity = bool(re.search(r"\b(then|after that|next|followed by|step)\b", lowered))
    return tone, urgency, decision, complexity


def build_profile(user_text: str) -> DeepUnderstandingProfile:
    """Build a deterministic, evidence-labelled profile for one turn."""
    tone, urgency, decision, complexity = _language_signals(user_text)
    capabilities = tuple(
        UnderstandingCapability(i, name, instruction, evidence, status)
        for i, (name, instruction, evidence, status) in enumerate(_CAPABILITY_ROWS, 1)
    )
    return DeepUnderstandingProfile(capabilities, tone, urgency, decision, complexity)
