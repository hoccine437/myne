# comms/firewall.py
"""Untrusted-input firewall — prompt-injection / social-engineering /
sensitive-request / link / attachment detection.

ARCHITECTURAL INVARIANT: external content is DATA. Nothing in comms ever
passes message text to an executor as instructions; this module classifies
flags only. Detection must be conservative on TWO ends: real attacks caught,
normal messages ("can you check the password policy?") not overflagged
(explicit request vs discussing the topic).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# instruction-override shapes (injection): imperative verbs targeting the
# assistant's rules/identity/permissions
_INJECTION_PATTERNS = (
    r"\bignore (your|all|the|previous|prior) (rules|instructions|guidelines)\b",
    r"\bforget (your|everything|your rules)\b",
    r"\byou are now\b", r"\bact as (the owner|admin|root)\b",
    r"\bpretend (you are|to be)\b", r"\bdev mode\b", r"\bjailbreak\b",
    r"\bdisable (security|safety|the constitution|verification)\b",
    r"\bbypass (the )?(constitution|security|approval|permission)\b",
    r"\bsend (this|it|that) to (everyone|all contacts|all my contacts)\b",
)

# requests ASKING for secrets of the user's (outbound-extraction attempts) —
# direct object required: "send me the password" is exfiltration; "should I
# change my password?" is not
_EXFIL_PATTERNS = (
    r"\b(send|tell|give|share|show)\w*\b.{0,30}\b(my|the|your) "
    r"(password|passcode|pin|otp|one[- ]time code|verification code|"
    r"api key|private key|seed phrase|recovery phrase|card number|cvv)\b",
    r"\bwhat('s| is) (my|the) (password|pin|otp)\b",
)

_SENSITIVE_CONTENT = (  # content that must never ride autonomous replies
    r"\bpassword\b", r"\botp\b", r"\bverification code\b", r"\bprivate key\b",
    r"\bseed phrase\b", r"\bcard number\b", r"\bcvv\b", r"\biban\b",
)

_LINK_RE = re.compile(r"https?://[^\s)\]>\"']+", re.I)

_DANGEROUS_ATTACH_EXT = frozenset({
    ".exe", ".apk", ".bat", ".cmd", ".ps1", ".sh", ".msi", ".jar", ".scr",
    ".com", ".vbs", ".js", ".wsf", ".hta", ".dll",
})


@dataclass(frozen=True)
class FirewallReport:
    injection: bool
    exfiltration: bool
    contains_sensitive: bool
    links: tuple
    link_domains: tuple
    dangerous_attachments: tuple
    trusted: bool    # False when ANY flag fired

    @property
    def flags(self) -> tuple:
        out = []
        if self.injection:
            out.append("injection")
        if self.exfiltration:
            out.append("exfiltration")
        if self.contains_sensitive:
            out.append("contains_sensitive")
        if self.link_domains:
            out.append("links")
        if self.dangerous_attachments:
            out.append("dangerous_attachment")
        return tuple(out)


def inspect_text(text: str) -> tuple:
    lowered = (text or "").lower()
    injection = any(re.search(p, lowered) for p in _INJECTION_PATTERNS)
    exfil = any(re.search(p, lowered) for p in _EXFIL_PATTERNS)
    sensitive = any(re.search(p, lowered) for p in _SENSITIVE_CONTENT)
    return injection, exfil, sensitive


def inspect(text: str, attachments: tuple = ()) -> FirewallReport:
    injection, exfil, sensitive = inspect_text(text)
    links = tuple(_LINK_RE.findall(text or ""))
    domains = []
    for link in links:
        m = re.match(r"https?://([^/]+)", link)
        if m:
            domains.append(m.group(1).lower())
    dangerous = tuple(
        (a or {}).get("name", "?") for a in (attachments or ())
        if isinstance(a, dict) and any(str((a.get("name") or "")).lower().endswith(ext)
                                       for ext in _DANGEROUS_ATTACH_EXT))
    return FirewallReport(
        injection=injection, exfiltration=exfil, contains_sensitive=sensitive,
        links=links, link_domains=tuple(domains),
        dangerous_attachments=dangerous,
        trusted=not (injection or exfil or sensitive or dangerous))
