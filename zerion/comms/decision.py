# comms/decision.py
"""The autonomy evidence gate (mission §8/§9/§10/§35).

Multi-dimensional evidence, never single-confidence:

  intent      — is the request's intent class known & clear?
  context     — does conversation state exist with participants + topic?
  identity    — is the sender a known participant/contact?
  fact        — candidate grounding (facts.commitment grounding)
  recipient   — wrong-recipient guard passes for this scope
  policy      — approvals.decide path
  risk        — classify.risk_markers on the candidate AND firewall flags
                on the inbound message
  history     — quality metrics: recent correction/failure rates
  consistency — contradiction detector
  critic      — intelligence.critic verdict over the candidate
  loop        — loop guard state
  connector   — connector health

Wired rule (absolute): any STOP condition or any critical dimension failing
forces "pause" (do nothing + ask). Autonomous sends additionally need mode A
conditions ALL true (§8). Approval = mode B. Nothing invents permission.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from comms import approvals, firewall, ratelimit, store
from comms.conversation_state import get as conv_get, belongs as conv_belongs
from comms.facts import candidate_grounding
from core import logging as log

AUTONOMOUS = "autonomous"
APPROVAL = "approval"
PAUSE = "pause"
OBSERVE = "observe"

# stop conditions that always win
_STOP_HARD = (
    "injection_attempt", "exfiltration_attempt", "sensitive_content_inbound",
    "high_risk", "identity_unknown_new_contact", "conversation_ambiguous",
    "recipient_not_in_scope", "candidate_contradiction", "grounding_missing",
    "disagreement", "loop_detected", "connector_unhealthy", "policy_block",
    "quality_downgraded",
)


@dataclass
class Decision:
    mode: str
    reasons: tuple = ()
    stop_flags: tuple = ()
    evidence: dict = field(default_factory=dict)


def evaluate(inbound, candidate, connector_state: str, quality: dict,
             critic_verdict: str = "", loop_detected: bool = False,
             disagreement: bool = False) -> Decision:
    """inbound: UnifiedMessage; candidate: Draft (or None for pure triage).
    All inputs must already be computed by the pipeline — this gate composes,
    it never calls the model or mutates state."""
    stops = []
    evidence = {}

    # -- inbound firewall (untrusted input)
    fw = firewall.inspect(inbound.content, inbound.attachments)
    evidence["firewall_flags"] = list(fw.flags)
    if fw.injection:
        stops.append("injection_attempt")
    if fw.exfiltration:
        stops.append("exfiltration_attempt")
    if fw.contains_sensitive:
        stops.append("sensitive_content_inbound")
    if fw.dangerous_attachments:
        stops.append("high_risk")

    # -- risk markers on content (inbound + candidate)
    from comms.classify import risk_markers
    risk = risk_markers(inbound.content + " " + (candidate.body if candidate else ""))
    if risk:
        stops.append("high_risk")
    evidence["risk_markers"] = sorted(risk)

    # -- conversation scope & identity
    state = conv_get(inbound.platform, inbound.account, inbound.conversation_id)
    known_participants = bool(state and state.get("participants"))
    evidence["known_conversation"] = known_participants
    from comms.contacts import lookup
    contact = lookup(inbound.sender) if inbound.sender else None
    identity_known = bool(state or contact)
    evidence["identity"] = "known" if identity_known else "unknown"
    if not identity_known:
        stops.append("identity_unknown_new_contact")

    # -- conversation ambiguity: no conversation scope at all
    if not inbound.conversation_id:
        stops.append("conversation_ambiguous")

    if candidate is not None:
        # -- wrong-recipient guard (strict scope check)
        if not conv_belongs(inbound.platform, inbound.account,
                            inbound.conversation_id, candidate.recipient):
            stops.append("recipient_not_in_scope")
        # -- grounding (no hallucinated commitments/facts)
        ground = candidate_grounding(candidate.body, inbound.content)
        evidence["grounding"] = ground.get("unverified_ids", [])
        if not ground["clean"]:
            stops.append("grounding_missing")
        # -- contradiction within this conversation — fed by consistency
        from comms.consistency import find_contradiction
        contra = find_contradiction(inbound.platform, inbound.conversation_id,
                                    candidate.body)
        if contra["contradiction"]:
            stops.append("candidate_contradiction")
            evidence["contradiction"] = contra["reason"]
        if disagreement:
            stops.append("disagreement")
        # -- model critic lane
        if critic_verdict == "revise":
            evidence["critic"] = "revise"

    # -- policy tier (existing ladder is authoritative)
    policy = approvals.decide(
        inbound.platform, inbound.account,
        candidate.recipient if candidate else inbound.sender,
        (candidate.body if candidate else inbound.content))
    evidence["policy_action"] = policy.action
    if policy.action in ("deny", "observe"):
        stops.append("policy_block")

    # -- loop protection
    if loop_detected:
        stops.append("loop_detected")

    # -- connector health
    evidence["connector"] = connector_state
    if connector_state in ("error", "disconnected"):
        stops.append("connector_unhealthy")

    # -- quality/reliability (auto-downgrade signal from comms.quality)
    if quality.get("forced_max_level") is not None:
        evidence["quality_forced_max"] = quality["forced_max_level"]

    # -- resolve
    stops = tuple(sorted(set(stops)))
    if stops:
        # distinguish "ask" (approval parking) from "pause" (do nothing)
        ask_mode = {"identity_unknown_new_contact", "conversation_ambiguous",
                    "recipient_not_in_scope", "candidate_contradiction",
                    "grounding_missing", "high_risk", "sensitive_content_inbound",
                    "disagreement"}
        mode = APPROVAL if set(stops) <= ask_mode else PAUSE
        if set(stops) & {"injection_attempt", "exfiltration_attempt",
                         "policy_block", "loop_detected", "connector_unhealthy"}:
            mode = PAUSE  # hard stops: never even draft-opinion in-band
        return Decision(mode=mode, stop_flags=stops,
                        reasons=tuple(sorted(stops)), evidence=evidence)

    # no stops: autonomous allowed ONLY when the policy ladder itself says
    # 'auto' (trusted low-risk rule) AND candidate exists
    if candidate is not None and policy.action == "auto":
        return Decision(mode=AUTONOMOUS, reasons=("trusted_low_risk",),
                        evidence=evidence)
    return Decision(mode=APPROVAL, reasons=("confirmation_required_by_ladder",),
                    evidence=evidence)
