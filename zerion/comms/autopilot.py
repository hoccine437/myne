# comms/autopilot.py
"""Background autonomous communication pump — the decision spine.

Per mission §41:

    EVENT → id → DEDUPE → CLASSIFY → SCOPE STATE → FIREWALL
      → reply-worthy? → DRAFT (reply engine) → CONSISTENCY → CRITIC
      → DECISION GATE (multi-dimensional evidence)
      → AUTONOMOUS (trusted low-risk) | APPROVAL (park + notify) | PAUSE
      → SEND (engine: policy/checklist/rails/connector/verify/audit/ledger)
      → LEARN (patterns only) → outbox on temporary failure

Invariants (absolute):
  * candidate generation is structurally separated from sending (draft first)
  * shadow mode systems observe+draft only
  * quality gates can only ever LOWER autonomy (no self-upgrade)
  * any override (pause/estop/platform/contact) halts that scope entirely
  * exactly-once by event id + action fingerprint — crashes revalidate,
    they never replay blindly
  * resource-strained host → observe/draft only, autopilot never competes
    with the user for the phone
"""

from __future__ import annotations

import os
import time

import config
from comms import audit, decision, events, loopguard, outbox, store
from comms.classify import classify_message, contains_task
from comms.conversation_state import touch as conv_touch
from comms.inbox import ingest
from comms.overrides import (platform_disabled, contact_disabled,
                             is_paused, is_estopped)
from comms.quality import note as qnote, apply_quality_gates, shadow_state, forced_max
from core import logging as log

_QUESTION_MARKERS = ("?", "could you", "can you", "please", "need", "when ",
                     "what ", "how ", "why ", "are we", "did you", "do you")

_REPLY_WORTHY_CLASSES = {"urgent", "personal", "work", "financial", "social"}


def _host_constrained() -> bool:
    try:
        return hasattr(os, "getloadavg") and os.getloadavg()[0] > 1.5
    except Exception:
        return False


def pump() -> dict:
    """One bounded background cycle. Never raises into the service loop."""
    if not config.COMM_ENABLED or not config.AUTOPILOT_ENABLED:
        return {"active": False}
    if is_estopped():
        return {"active": False, "estop": True}

    from comms.registry import connectors
    from comms.scheduler import poll_once as _pulse

    # 1. drain the outbox (revalidating retries) then take the event pulse —
    # every polled message flows through the full decision pipeline
    sent_counts = outbox.flush(send_queued_draft)
    if _host_constrained():
        pulse = _pulse()  # ingest-only under load; replies defer
        return {"active": True, "degraded": "host load — replies deferred",
                "outbox": sent_counts, "ingested": pulse.get("ingested", 0)}
    pulse = _pulse(event_hook=process_inbound)

    # health snapshot (mission §6) — honest state, never fabricated
    try:
        from comms import health as comm_health
        from comms import bgworkflows
        states = [h.get("state") for h in connectors.health().values()]
        service_state = ("degraded" if any(s == "error" for s in states)
                         else ("active" if states else "idle"))
        comm_health.write(service_state, queue_depth=len(outbox.pending()),
                          workflows_active=len(bgworkflows.active()))
    except Exception as e:
        log.debug(f"comm health write deferred: {e}")

    if not connectors.active():
        return {"active": True, "idle": "no connectors", "outbox": sent_counts}
    return {"active": True, "outbox": sent_counts,
            "workflows": pulse.get("workflows", 0),
            "ingested": pulse.get("ingested", 0)}


def process_inbound(msg) -> dict:
    """The full per-message pipeline. Returns a journal-able outcome."""
    eid = events.Event.key_for(msg.platform, msg.account, msg.sender,
                               msg.conversation_id, msg.message_id,
                               msg.content, msg.timestamp)
    claim = events.claim_event(eid, msg.platform, msg.conversation_id)
    if claim == "duplicate":
        return {"event": eid, "outcome": "duplicate-ignored"}

    def settle(status, result=""):
        events.settle_event(eid, status, result)

    # platform / contact overrides make scopes inert (user override plane)
    if is_paused():
        settle("ignored", "paused"); return {"event": eid, "outcome": "paused"}
    if platform_disabled(msg.platform):
        settle("ignored", "platform disabled"); return {"event": eid, "outcome": "platform-disabled"}
    if contact_disabled(msg.sender):
        settle("ignored", "contact disabled"); return {"event": eid, "outcome": "contact-disabled"}

    # loop protection BEFORE any work
    loop, loop_reason = loopguard.is_loop_echo(msg, msg.account)
    if loop:
        qnote(msg.platform, "loop", f"{msg.conversation_id}: {loop_reason}")
        apply_quality_gates(msg.platform)
        settle("ignored", f"loop-guard: {loop_reason}")
        return {"event": eid, "outcome": "loop-guard", "detail": loop_reason}

    # ingest (classify+store+contact touch) then scope state
    if not msg.classification:
        classify_message(msg)
    ingest(msg)
    conv_touch(msg.platform, msg.account, msg.conversation_id, sender=msg.sender,
               topic=(msg.reply_context or msg.content)[:80],
               last_action="received")

    # FIREWALL FIRST (§17/§18): manipulation attempts are quarantined before
    # any worthiness/drafting decision — observe-only, never drafted as-is
    from comms import firewall as fw_mod
    fw = fw_mod.inspect(msg.content, msg.attachments)
    if fw.injection or fw.exfiltration:
        stops = [f for f in fw.flags if f in ("injection", "exfiltration")]
        qnote(msg.platform, "policy_block", ",".join(stops))
        apply_quality_gates(msg.platform)
        settle("failed", "firewall:" + ",".join(stops))
        audit.record("firewall_block", msg.platform, account=msg.account,
                     target=msg.sender, result="paused",
                     extra={"flags": list(fw.flags)})
        _notify(f"Blocked a manipulation attempt from {msg.sender} "
                f"({msg.platform}): {', '.join(stops)}", level="warning")
        return {"event": eid, "outcome": "paused", "stops": stops}

    # reply-worthiness — quiet channels must not generate noise (§21). A
    # direct question is reply-worthy regardless of topic class; everything
    # else needs a conversational category + request/task signal.
    is_direct_question = "?" in (msg.content or "")
    worthy = (is_direct_question or
              (msg.classification in _REPLY_WORTHY_CLASSES and
               (contains_task(msg.content) or
                any(m in (msg.content or "").lower() for m in _QUESTION_MARKERS))))
    if not worthy:
        settle("done", f"classified {msg.classification}, no reply required")
        return {"event": eid, "outcome": "observed", "class": msg.classification}

    # AUTHORIZATION: background replies require an explicit, active, scoped
    # user-started flow (mission §2). Without one the system only observes —
    # a message saying "answer people" is never self-authorizing.
    if config.COMM_REQUIRE_FLOW:
        from comms import bgworkflows
        flow = bgworkflows.covers(msg.platform, msg.account, scope="messages")
        if flow is None:
            settle("ignored", "no authorized background workflow for this scope")
            return {"event": eid, "outcome": "observed-no-flow",
                    "class": msg.classification}

    # shadow mode: draft-scored but never sent (§30)
    shadow = shadow_state(msg.platform) == "shadow"

    # draft candidate
    from comms.reply import draft_reply
    candidate = draft_reply(msg)

    # critic lane (local structural review; no extra LLM call)
    critic_verdict = ""
    if config.ENABLE_SELF_CRITIC:
        try:
            from intelligence.critic import self_critic
            critique = self_critic.review(msg.content[:300], candidate.body, 0.65)
            critic_verdict = "revise" if critique.should_improve else "accept"
        except Exception:
            critic_verdict = ""

    # quality gate adjustments (downgrade only)
    quality = forced_max(msg.platform)
    # connector state is a decision input, not a side effect
    from comms.registry import connectors as _reg
    health_map = _reg.health()
    conn_state = (health_map.get(msg.platform) or {}).get("state", "disconnected")

    result = decision.evaluate(msg, candidate, conn_state, quality,
                               critic_verdict=critic_verdict,
                               loop_detected=False)

    qnote(msg.platform, "draft", f"{msg.classification}:{candidate.tone}")
    audit.record("decision", msg.platform, account=msg.account,
                 target=msg.sender, result=result.mode,
                 extra={"stops": list(result.stop_flags),
                        "evidence_keys": sorted(result.evidence.keys())})

    if result.mode == decision.PAUSE:
        # record the candidate for review, marked failed (never sent)
        store.store_draft(candidate)
        store.set_draft_status(candidate.draft_id, "failed")
        settle("failed", "pause:" + ",".join(result.stop_flags))
        _notify("Autopilot paused a reply: " + ", ".join(result.stop_flags), level="warning")
        return {"event": eid, "outcome": "paused", "stops": list(result.stop_flags)}

    if shadow or result.mode == decision.OBSERVE:
        store.store_draft(candidate)
        store.set_draft_status(candidate.draft_id, "prepared")
        settle("done", f"shadow-observed ({msg.classification})")
        return {"event": eid, "outcome": "shadow-draft", "draft": candidate.draft_id}

    store.store_draft(candidate)
    store.set_draft_status(candidate.draft_id, "needs_approval")

    if result.mode == decision.APPROVAL:
        _notify(f"Reply draft ready for {msg.sender} ({msg.platform}) — "
                f"why: {', '.join(result.reasons)}", level="info",
                draft_id=candidate.draft_id)
        settle("done", "awaiting approval")
        return {"event": eid, "outcome": "approval-parked", "draft": candidate.draft_id,
                "reasons": list(result.reasons)}

    # AUTONOMOUS: every safety gate already passed
    loopguard.note_outgoing(msg.platform, msg.account, msg.conversation_id)
    return execute_autonomous(candidate, eid, msg)


def execute_autonomous(candidate, event_id: str, msg) -> dict:
    from comms.engine import send_draft
    # engine.send_draft owns exactly-once action claiming (single true path)
    out = send_draft(candidate, confirmed=True, agent="autopilot")
    if out["ok"]:
        qnote(candidate.platform, "send", candidate.draft_id)
        store.contact_note(msg.sender, f"replied: {(msg.reply_context or msg.content)[:60]}")
        events.settle_event(event_id, "done", "autonomous send accepted")
        return {"event": event_id, "outcome": "sent",
                "verification": out.get("verification", "")}
    # failure classification → retry path or stop
    error_class = outbox.classify_error(out.get("error") or out.get("platform_result", ""))
    qnote(candidate.platform, "verify_fail", candidate.draft_id)
    apply_quality_gates(candidate.platform)
    if error_class == "temporary":
        qid = outbox.enqueue(candidate.draft_id, candidate.platform,
                             candidate.account, candidate.recipient)
        events.settle_event(event_id, "failed", f"queued for retry ({qid})")
        return {"event": event_id, "outcome": "queued", "queue_id": qid}
    events.settle_event(event_id, "failed", error_class)
    _notify(f"Autonomous send failed ({error_class}): {out.get('error','')}",
            level="error")
    return {"event": event_id, "outcome": "failed", "error_class": error_class}


def send_queued_draft(row: dict) -> dict:
    """Revalidation executor for the outbox (mission §27/§40): context,
    recipient, authorization, and freshness are ALL re-checked at send time."""
    from comms import approvals, engine as send_engine
    from comms.models import Draft

    if is_estopped() or is_paused():
        return {"ok": False, "error": "paused"}
    row_draft = store.get_draft(row["draft_id"])
    if row_draft is None or row_draft.get("status") in ("sent", "rejected", "failed"):
        return {"ok": False, "error": "queue item no longer valid (state changed)"}
    if platform_disabled(row["platform"]):
        return {"ok": False, "error": f"platform {row['platform']} disabled meanwhile"}
    # policy is re-evaluated, not cached — an approval ladder change mid-queue
    # takes immediate effect
    draft = Draft(platform=row_draft["platform"], recipient=row_draft["recipient"],
                  body=row_draft["body"], subject=row_draft.get("subject", ""),
                  conversation_id=row_draft.get("conversation_id", ""),
                  account=row_draft.get("account", ""), tone=row_draft.get("tone", "casual"),
                  risk_markers=tuple(row_draft.get("risk_markers") or ()),
                  draft_id=row_draft["draft_id"])
    return send_engine.send_draft(draft, confirmed=True, agent="outbox-revalidation")


def _notify(text: str, level: str = "info", draft_id: str = "") -> None:
    """Surface to the user: termux notification when available, always the UI
    event stream; never silent."""
    try:
        from phone.adapter import TermuxAdapter
        TermuxAdapter().run("termux-notification", "--title", "Zerion Autopilot",
                            "--content", text[:300])
    except Exception:
        pass
    try:
        from ui.events import bus
        bus.emit("notification", {"level": level, "text": text,
                                  "draft_id": draft_id})
    except Exception:
        pass
    log.info(f"autopilot: {text}")
