# comms/ratelimit.py
"""Anti-spam rails — Zerion must never become a spam engine.

Enforced per send, from the ledger in comm_send_log:
  * platform rate window (COMM_RATE_PER_MINUTE)
  * recipient cooldown (COMM_RECIPIENT_COOLDOWN seconds between sends
    to the same recipient on any platform)
  * mass-recipient cap (COMM_MAX_RECIPIENTS — also enforced by approvals)
  * duplicate content detection (same content hash, same recipient,
    inside COMM_DUPLICATE_WINDOW)

Deny is fail-closed: any ledger error returns allowed=False so sending
stops rather than flooding silently. All state lives in the existing DB;
nothing is held in process memory where a restart would dodge the rail.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

import config
from comms import store


@dataclass(frozen=True)
class Rail:
    allowed: bool
    reason: str


def content_hash(body: str) -> str:
    return hashlib.sha256((body or "").strip().lower().encode("utf-8")).hexdigest()[:24]


def check(platform: str, recipient: str, body: str,
          recipient_count: int = 1) -> Rail:
    now = time.time()
    if recipient_count > config.COMM_MAX_RECIPIENTS:
        return Rail(False, f"recipient cap exceeded ({recipient_count} > "
                           f"{config.COMM_MAX_RECIPIENTS}) — refusing mass send")
    try:
        recent_platform = store.sends_since(platform, now - 60)
        if len(recent_platform) >= config.COMM_RATE_PER_MINUTE:
            return Rail(False, f"platform rate limit: {len(recent_platform)} sends "
                               f"in the last minute (cap {config.COMM_RATE_PER_MINUTE})")
        body_hash = content_hash(body)
        dupes = [r for r in store.sends_since(platform,
                                              now - config.COMM_DUPLICATE_WINDOW)
                 if r["recipient"] == recipient and r["content_hash"] == body_hash]
        if dupes:
            return Rail(False, "duplicate send detected inside "
                               f"{config.COMM_DUPLICATE_WINDOW}s window")
        if recipient and config.COMM_RECIPIENT_COOLDOWN:
            recent_recipient = store.sends_to_since(recipient,
                                                    now - config.COMM_RECIPIENT_COOLDOWN)
            if recent_recipient:
                wait = int(config.COMM_RECIPIENT_COOLDOWN -
                           (now - recent_recipient[-1]["ts"]))
                return Rail(False, f"recipient cooldown: {max(1, wait)}s before another "
                                   f"message to this recipient")
    except Exception as exc:
        return Rail(False, f"rate-limit ledger unavailable (fail-closed): {exc}")
    return Rail(True, "within limits")


def record(platform: str, recipient: str, body: str,
           draft_id: str = "", result: str = "") -> None:
    store.log_send(platform, recipient, content_hash(body), draft_id, result)
