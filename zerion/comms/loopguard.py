# comms/loopguard.py
"""Loop protection (mission §25): Zerion's own output must never become its
next input's trigger.

Signals:
- echo fingerprints: an inbound item whose normalized content matches one of
  OUR recent sends in the same conversation
- self-originated markers: known agent/bot sender names, our own account
- cycle counting per conversation: N bot-ish exchanges inside a window

Hard stop after MAX_CYCLES in MAX_WINDOW seconds: that conversation goes
cooldown until the user clears it, and every stop is audited.
"""

from __future__ import annotations

import time

from comms import audit, store
from comms.events import content_norm

MAX_CYCLES = 6
CYCLE_WINDOW = 300          # 5 minutes
COOLDOWN = 900              # 15 minutes

# in-process cycle state (per scope); short-lived by design — a restart
# RESUMES conversation flow conservatively (fresh counters = more asking,
# never more sending)
_cycles: dict = {}
_cooldowns: dict = {}

_BOT_MARKERS = ("[bot]", "via zerion", "auto-reply", "[draft-local]")


def is_loop_echo(inbound, account: str) -> tuple:
    """(is_loop, reason). Content-echo of our own recent sends OR a known
    self/bot sender OR runaway cycle counting."""
    scope = f"{inbound.platform}|{inbound.account or account}|{inbound.conversation_id}"

    if scope in _cooldowns and time.time() < _cooldowns[scope]:
        return True, f"conversation in loop cooldown for {int(_cooldowns[scope] - time.time())}s"

    # self echo: sender is our own account or carries bot markers
    sender_norm = (inbound.sender or "").lower()
    if account and sender_norm == (account or "").lower():
        _note_cycle(scope)
        return True, "message originated from our own account"
    if any(m in (inbound.content or "").lower() for m in _BOT_MARKERS):
        _note_cycle(scope)
        return True, "bot-marker content (self or other automation)"

    # content echo: identical normalized body as one of our recent sends
    try:
        from comms import ratelimit  # ledger in comm_send_log
        recent = store.sends_since(inbound.platform, time.time() - CYCLE_WINDOW)
        norm = content_norm(inbound.content)
        for row in recent:
            # ledger stores hashes only — compare hash of normalized content
            from comms.ratelimit import content_hash
            if row["recipient"] in (inbound.conversation_id, inbound.sender) and \
               row["content_hash"] == content_hash(inbound.content):
                _note_cycle(scope)
                return True, "inbound echoes a message we just sent here"
    except Exception:
        pass

    if _cycles.get(scope, {}).get("count", 0) >= MAX_CYCLES:
        _cooldowns[scope] = time.time() + COOLDOWN
        audit.record("loop_guard", inbound.platform,
                     account=inbound.account, target=inbound.sender,
                     result="cooldown", error=f">{MAX_CYCLES} cycles in {CYCLE_WINDOW}s")
        return True, f"cycle limit ({MAX_CYCLES}/{CYCLE_WINDOW}s) hit — cooling down"

    return False, ""


def note_outgoing(platform: str, account: str, conversation_id: str) -> None:
    scope = f"{platform}|{account or ''}|{conversation_id}"
    _note_cycle(scope)


def _note_cycle(scope: str) -> None:
    now = time.time()
    entry = _cycles.setdefault(scope, {"start": now, "count": 0})
    if now - entry["start"] > CYCLE_WINDOW:
        entry.update(start=now, count=0)
    entry["count"] += 1


def clear(scope: str) -> None:
    _cycles.pop(scope, None)
    _cooldowns.pop(scope, None)
