# comms/approvals.py
"""Approval ladder for outbound communication.

LEVEL 0 — OBSERVE:   read/classify/summarize only.
LEVEL 1 — DRAFT:     may prepare drafts; nothing leaves the device.
LEVEL 2 — CONFIRM:   prepare → show user → explicit approval → send.
LEVEL 3 — TRUSTED:   auto-send ONLY for entries in config.COMM_TRUSTED
                     (exact {platform, account, recipient} allowlist rules),
                     and only when the draft carries NO risk markers.

Escalation is one-way: risk markers (financial/credentials/legal/sensitive/
irreversible/mass) always force at least LEVEL 2 semantics, even on L3 rules.

Revocation: dropping a policy scope or setting it to 0/1 blocks new sends
immediately; drafts already prepared become plain text again (status stays
needs_approval). Nothing here ever stores or logs secrets.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import config
from comms import store
from comms.classify import risk_markers

LEVEL_OBSERVE = 0
LEVEL_DRAFT = 1
LEVEL_CONFIRM = 2
LEVEL_TRUSTED = 3


@dataclass(frozen=True)
class PolicyDecision:
    action: str            # "observe" | "draft" | "confirm" | "auto" | "deny"
    required_level: int
    effective_level: int
    reason: str
    risk: tuple = ()


def _trusted_rules() -> list:
    try:
        rules = json.loads(config.COMM_TRUSTED_RAW or "[]")
        return [r for r in rules if isinstance(r, dict)]
    except Exception:
        return []


def effective_level(platform: str, account: str = "") -> int:
    """Most specific scope wins: account > platform > global default."""
    for scope in (f"account:{account}" if account else None,
                  f"platform:{platform}"):
        if scope:
            level = store.get_policy_level(scope)
            if level is not None:
                return max(0, min(3, level))
    return config.COMM_DEFAULT_LEVEL


def set_level(platform: str, level: int, account: str = "") -> dict:
    scope = f"account:{account}" if account else f"platform:{platform}"
    store.set_policy_level(scope, int(max(0, min(3, level))))
    return {"scope": scope, "level": effective_level(platform, account)}


def revoke(platform: str, account: str = "") -> dict:
    scope = f"account:{account}" if account else f"platform:{platform}"
    store.drop_policy(scope)
    return {"scope": scope, "revoked": True,
            "level": effective_level(platform, account)}


def decide(platform: str, account: str, recipient: str, text: str,
           recipient_count: int = 1, workflow: str = "") -> PolicyDecision:
    """What may happen to this outbound item, right now."""
    risk = risk_markers(text or "")
    if recipient_count > 1 or recipient_count > config.COMM_MAX_RECIPIENTS:
        risk = tuple(set(risk) | {"mass"})

    level = effective_level(platform, account)

    # hard stops regardless of level
    if not config.COMM_ENABLED:
        return PolicyDecision("deny", LEVEL_CONFIRM, level,
                              "communication layer disabled", risk)
    if recipient_count > config.COMM_MAX_RECIPIENTS:
        return PolicyDecision(
            "deny", LEVEL_CONFIRM, level,
            f"recipient count {recipient_count} exceeds cap "
            f"{config.COMM_MAX_RECIPIENTS} (anti-spam rail)", risk)
    if level <= LEVEL_OBSERVE:
        return PolicyDecision("observe", LEVEL_CONFIRM, level,
                              "scope is observe-only", risk)
    if level == LEVEL_DRAFT:
        return PolicyDecision("draft", LEVEL_CONFIRM, level,
                              "draft-only scope: user must upgrade or confirm later", risk)

    # level >= 2: risk markers force human confirmation even on trusted rules
    if risk:
        return PolicyDecision("confirm", LEVEL_CONFIRM, level,
                              "risk marker(s) present: " + ", ".join(sorted(risk)), risk)

    if level >= LEVEL_TRUSTED:
        for rule in _trusted_rules():
            if rule.get("platform") == platform and \
               (not rule.get("account") or rule.get("account") == account) and \
               (not rule.get("recipient") or rule.get("recipient") == recipient):
                return PolicyDecision("auto", LEVEL_TRUSTED, level,
                                      "trusted low-risk rule matched (audited)", risk)

    return PolicyDecision("confirm", LEVEL_CONFIRM, level,
                          "explicit confirmation required before sending", risk)
