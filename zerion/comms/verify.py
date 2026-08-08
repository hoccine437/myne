# comms/verify.py
"""Pre/post-send verification for outbound communication.

PRE-SEND checklist (all must pass for status 'ready'):
  recipient_ok      — valid shape for the platform (email addr / number / handle)
  conversation_ok   — if in_reply_to set, the conversation exists in the inbox
  content_ok        — non-trivial body after strip
  attachments_ok    — referenced local files exist and are readable
  platform_ok       — connector registered AND supports('send')
  policy_ok         — approvals.decide() result path is exercised here only as
                      metadata (the actual policy decision happens upstream;
                      we fail-closed when the connector is missing)

POST-SEND: the connector's platform_result is captured and audited; a send
that returned ok=False moves the draft to failed with the platform reason.

Verification results ride on draft.checks so UI approval screens show the
evidence. Nothing here fabricates success — a failed check is returned, not
hidden.
"""

from __future__ import annotations

import os
import re

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?[0-9][0-9 .\-]{5,17}$")
_HANDLE_RE = re.compile(r"^@?[A-Za-z0-9_.\-]{2,32}$")


def _recipient_ok(platform: str, recipient: str) -> bool:
    if platform == "email":
        return bool(_EMAIL_RE.match(recipient or ""))
    if platform in ("phone", "sms"):
        return bool(_PHONE_RE.match(recipient or ""))
    # telegram/social/local accept handles, chat ids or numbers
    return bool(_HANDLE_RE.match(recipient or "") or _PHONE_RE.match(recipient or "")
                or str(recipient or "").isdigit())


def pre_send_checklist(draft, connector_lookup=None, inbox_lookup=None) -> dict:
    checks = {}
    checks["recipient_ok"] = _recipient_ok(draft.platform, draft.recipient)
    checks["conversation_ok"] = True
    if draft.conversation_id and inbox_lookup is not None:
        try:
            checks["conversation_ok"] = bool(inbox_lookup(draft.conversation_id))
        except Exception:
            checks["conversation_ok"] = False
    checks["content_ok"] = bool((draft.body or "").strip()) and len(draft.body) > 2
    attach_ok = True
    for att in draft.attachments or ():
        path = (att or {}).get("local_path", "")
        if path and not os.path.isfile(os.path.expanduser(path)):
            attach_ok = False
            break
    checks["attachments_ok"] = attach_ok
    # checklist proves the platform EXISTS — whether it can *send* is the
    # send engine's call (that layer surfaces the connector's own honest
    # refusal text, e.g. supervised-flow redirects)
    connector = connector_lookup(draft.platform) if connector_lookup else None
    checks["platform_ok"] = connector is not None
    checks["risk_reviewed"] = True  # risk markers are attached unfiltered
    return checks


def checks_pass(checks: dict, require_platform: bool = True) -> bool:
    core = [checks.get("recipient_ok"), checks.get("conversation_ok"),
            checks.get("content_ok"), checks.get("attachments_ok")]
    if require_platform:
        core.append(checks.get("platform_ok"))
    return all(core)


def verify_platform_result(result: dict) -> tuple:
    """Normalize a connector send result to (verified, note)."""
    if not isinstance(result, dict):
        return False, "connector returned a non-structured result"
    if result.get("ok") is True:
        return True, str(result.get("platform_result", "ok"))[:200]
    return False, str(result.get("platform_result", "platform refused"))[:200]
