# comms/scheduler.py
"""Trigger pump: polls OUTSIDE-IN events from active connectors + calendar
dues, feeds them to inbox ingestion, and runs enabled workflows whose
trigger matches. Called by the 24/7 service maintenance cadence and by the
workflow_run tool (manual trigger), so behavior is identical supervised or
on-demand. Fully offline-safe: with no configured connectors it is a no-op.
"""

from __future__ import annotations

import time

import config
from comms import store
from comms.inbox import ingest
from comms.registry import connectors
from comms.workflow import engine, eval_condition
from core import logging as log

_TRIGGER_PLATFORM = {"email.new": "email", "telegram.new": "telegram",
                     "notification.new": ("phone", "social")}


def poll_once(event_hook=None) -> dict:
    """One bounded sweep. Returns counts — always, even when everything is
    degraded. Nothing in here may raise into the service loop.

    event_hook(msg) replaces the default ingest() per polled item — the
    autopilot passes its full decision pipeline; standalone callers keep the
    ingest-only behavior exactly as before."""
    if not config.COMM_ENABLED:
        return {"polled": 0, "ingested": 0, "workflows": 0, "idle": "comm disabled"}
    hook = event_hook or (lambda m: ingest(m))
    ingested = 0
    polled = 0
    try:
        if not connectors.active():
            return {"polled": 0, "ingested": 0, "workflows": 0,
                    "idle": "no connectors configured"}
        for msg in connectors.poll_all_events():
            polled += 1
            hook(msg)
            ingested += 1
    except Exception as e:
        log.warning(f"comm poll degraded: {e}")

    fired = 0
    events = []
    for row in store.query_messages(limit=25):
        events.append({"type": f"{row['platform']}.new", "message_row": row,
                       "summary": f"{row['platform']}: {row['sender']}: {row['content'][:80]}"})
    # calendar dues are events too
    try:
        from comms import calendar
        for ev in calendar.due_reminders():
            events.append({"type": "calendar.soon", "calendar_event": ev,
                           "summary": f"calendar: {ev['title']}"})
    except Exception:
        pass

    for wf in store.list_workflows(enabled_only=True):
        definition = wf.get("definition") or {}
        trigger = definition.get("trigger") or {}
        want = trigger.get("type")
        match = trigger.get("match") or {}
        for event in events:
            platform_match = _TRIGGER_PLATFORM.get(want or "", None)
            if want == "schedule":
                pass  # schedule triggers fire unconditionally on cadence
            elif want == "calendar.soon" and event["type"] != "calendar.soon":
                continue
            elif platform_match is not None:
                ps = (platform_match,) if isinstance(platform_match, str) else platform_match
                if event["type"].split(".")[0] not in ps:
                    # messages poll raw: event.type is platform.new per row platform
                    if event.get("message_row", {}).get("platform") not in ps:
                        continue
            elif want in ("command", "event"):
                continue  # manual invocation only
            # trigger match conditions (sender contains, keyword, urgency...)
            row = event.get("message_row") or {}
            ctx_row = {"event": {"summary": event.get("summary", ""),
                                 "sender": row.get("sender", ""),
                                 "platform": row.get("platform", ""),
                                 "classification": row.get("classification", ""),
                                 "urgency": row.get("urgency", ""),}}
            if match and not all(eval_condition({"field": f"event.{k}",
                                                 "op": spec.get("op", "contains"),
                                                 "value": spec.get("value")}
                                                if isinstance(spec, dict) else
                                                {"field": f"event.{k}", "op": "contains", "value": spec},
                                                ctx_row)
                                 for k, spec in match.items()):
                continue
            # hydrate real message for steps that need it
            msg_obj = None
            if row:
                from comms.models import UnifiedMessage
                msg_obj = UnifiedMessage(
                    platform=row["platform"], account=row.get("account", ""),
                    sender=row.get("sender", ""), content=row.get("content", ""),
                    conversation_id=row.get("conversation_id", ""),
                    reply_context=row.get("reply_context", ""),
                    classification=row.get("classification", ""),
                    urgency=row.get("urgency", ""),
                    timestamp=row.get("timestamp", time.time()))
            try:
                engine.run(definition, {"type": want, "message": msg_obj,
                                        "summary": event.get("summary", "")},
                           workflow_id=wf["workflow_id"])
                fired += 1
            except Exception as e:
                log.warning(f"workflow {wf['name']} run failed: {e}")
            break  # one event per workflow per sweep — keeps the loop bounded

    return {"polled": polled, "ingested": ingested, "workflows": fired,
            "events_seen": len(events)}
