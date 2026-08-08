# comms/classify.py
"""Local, zero-cost message classification + risk detection.

Categories: urgent | personal | work | financial | social | system | spam | low.
Urgency:    low | normal | high | urgent.
Risk flags drive the approval ladder (comms/approvals.py) — a flag can only
ever RAISE the required confirmation level, never lower it.

All rules are transparent keyword/structure heuristics — no LLM cost, no
black box, and the result is attached to the message so later steps
(draft/plan/notify) see the same judgement.
"""

from __future__ import annotations

import re

from comms.models import UnifiedMessage

_CATEGORY_KEYWORDS = {
    "urgent": ("urgent", "asap", "immediately", "emergency", "deadline today",
               "critical", "right now", "last warning", "action required"),
    "financial": ("invoice", "payment", "receipt", "bank", "transfer", "salary",
                  "bill", "charged", "refund", "price", "quote", "contract value"),
    "work": ("meeting", "standup", "review", "deployment", "pull request",
             "ticket", "project", "manager", "client", "deliverable", "sprint",
             "can we meet", "schedule a call"),
    "personal": ("family", "mom", "dad", "brother", "sister", "birthday",
                 "dinner", "doctor", "appointment"),
    "social": ("liked", "followed", "commented", "mentioned you", "tagged",
               "friend request", "new follower", "replied to your"),
    "system": ("security alert", "sign-in", "password", "verification code",
               "login", "backup", "update available", "2fa", "one-time"),
    "spam": ("unsubscribe", "winner", "lottery", "free money", "click here",
             "limited offer", "act now", "risk-free", "guaranteed",
             "you have been selected", "crypto giveaway"),
}

_URGENCY_HIGH = ("today", "this week", "soon", "please respond", "waiting",
                 "follow up", "follow-up", "can we meet", "tomorrow")

# High-risk markers: presence of ANY of these forces confirmation level >= 2
# regardless of configured platform level (money, credentials, legal, mass,
# irreversible, sensitive) — comms/approvals.py enforces.
HIGH_RISK_KEYWORDS = {
    "financial": ("invoice", "payment", "pay ", "bank transfer", "wire",
                  "purchase", "order now", "card number", "iban", "crypto wallet"),
    "credentials": ("password", "passphrase", "pin code", "api key", "secret",
                    "login link", "reset password", "otp", "verification code"),
    "legal": ("contract", "agreement", "terms and conditions", "sign here",
              "liability", "lawsuit", "gdpr", "nda"),
    "sensitive": ("medical", "diagnosis", "id number", "passport", "ssn",
                  "address is", "date of birth"),
    "irreversible": ("delete account", "close account", "cancel subscription",
                     "erase", "terminate", "unrecoverable"),
}


def _matches(marker: str, lowered: str) -> bool:
    """Word/phrase boundary match: 'nda' must not fire inside 'calendar',
    'pin' must not fire inside 'shipping'. Multi-word phrases match as-is."""
    return bool(re.search(rf"\b{re.escape(marker)}\b", lowered))


def _scan(text: str, table) -> list:
    lowered = (text or "").lower()
    return [name for name, markers in table.items()
            if any(_matches(m, lowered) for m in markers)]


def classify_message(msg: UnifiedMessage) -> UnifiedMessage:
    text = f"{msg.reply_context} {msg.content}"
    lowered = text.lower()

    # spam beats everything else for the category (it defines the response)
    for category in ("spam", "urgent", "financial", "system", "work",
                     "personal", "social"):
        if category in _scan(text, {category: _CATEGORY_KEYWORDS[category]}):
            msg.classification = category
            break
    else:
        msg.classification = "low"

    if msg.classification == "urgent":
        msg.urgency = "urgent"
    elif any(m in lowered for m in _URGENCY_HIGH) or msg.classification in (
            "financial", "system"):
        msg.urgency = "high"
    elif msg.classification in ("spam", "low", "social"):
        msg.urgency = "low"
    else:
        msg.urgency = "normal"

    return msg


def risk_markers(text: str) -> tuple:
    """Which high-risk families a text touches. Empty tuple = low risk."""
    return tuple(_scan(text, HIGH_RISK_KEYWORDS))


def contains_task(text: str) -> bool:
    """Cheap task/obligation signal: imperative + deadline/request shape."""
    lowered = (text or "").lower()
    return bool(re.search(r"\b(please|could you|can you|need to|must|todo|to do|"
                          r"remind me|schedule|book|call|send me|send us)\b", lowered))


def extract_dates(text: str) -> list:
    """Lightweight date mentions — ISO dates and relative words; the parser
    upstream (calendar) decides what to do with them."""
    out = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text or "")
    for rel in ("tomorrow", "today", "next week", "tonight", "this friday",
                "this monday", "this weekend"):
        if rel in (text or "").lower():
            out.append(rel)
    return out
