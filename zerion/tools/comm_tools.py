# tools/comm_tools.py
"""Communication tools — the Core's (and the LLM's) only handle on the
Communication Layer. Every consequential tool is marked destructive so it
flows through the existing Constitution policy check + single-slot
confirmation flow; read tools stay freely callable (agents may use them).
"""

from __future__ import annotations

import json
import time

from tools.base import Tool, ToolResult


class CommInboxTool(Tool):
    name = "comm_inbox"
    description = ("Read the unified communication inbox (email / telegram / "
                   "phone / social / calendar items normalized). Params: "
                   "optional platform, optional query, optional limit (max 50).")
    parameters = {"platform": "optional: email|telegram|phone|social|calendar",
                  "query": "optional text filter", "limit": "optional int"}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        from comms.inbox import search, summarize
        p = parameters or {}
        limit = min(int(p.get("limit") or 25), 50)
        query = str(p.get("query") or "")
        platform = str(p.get("platform") or "")
        if query:
            rows = search(query, platform=platform, limit=limit)
            if not rows:
                return ToolResult.ok(message="No matching messages.")
            lines = [f"[{r['platform']}] {r['sender']}: "
                     f"{(r['content'] or r['reply_context'])[:120]}" for r in rows]
            return ToolResult.ok(data={"count": len(rows)}, message="\n".join(lines))
        return ToolResult.ok(message=summarize(platform=platform, limit=limit))


class CommDraftTool(Tool):
    name = "comm_draft"
    description = ("Draft a reply to an inbound message: provide the message "
                   "stable_id (from comm_inbox) or a platform+recipient+text "
                   "to draft from scratch. The draft is stored and shown for "
                   "approval; nothing is sent by this tool.")
    parameters = {"stable_id": "optional — the inbound message to answer",
                  "platform": "required for scratch drafts",
                  "recipient": "required for scratch drafts",
                  "text": "the point to convey (natural language)",
                  "tone": "optional: casual|professional|urgent|technical"}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        from comms import approvals, store
        from comms.models import UnifiedMessage, Draft
        from comms.reply import draft_reply
        p = parameters or {}

        msg = None
        stable_id = str(p.get("stable_id") or "")
        if stable_id:
            rows = store.query_messages("stable_id=?", (stable_id,), 1)
            if not rows:
                return ToolResult.fail("not_found", f"no message with id {stable_id}")
            r = rows[0]
            msg = UnifiedMessage(
                platform=r["platform"], account=r.get("account", ""),
                sender=r.get("sender", ""), content=r.get("content", ""),
                conversation_id=r.get("conversation_id", ""),
                reply_context=r.get("reply_context", ""),
                classification=r.get("classification", ""),
                urgency=r.get("urgency", ""), timestamp=r.get("timestamp", time.time()))
        else:
            platform = str(p.get("platform") or "").strip()
            recipient = str(p.get("recipient") or "").strip()
            text = str(p.get("text") or "").strip()
            if not (platform and recipient and text):
                return ToolResult.fail("missing_parameter",
                                       "scratch drafts need platform + recipient + text")
            msg = UnifiedMessage(platform=platform, account=str(p.get("account", "")),
                                 sender=recipient, content=text,
                                 reply_context=str(p.get("subject", "")))

        # policy: drafting is LEVEL 1+ behavior; observe-only scopes refuse
        decision = approvals.decide(msg.platform, msg.account, msg.sender, msg.content)
        if decision.action == "observe":
            return ToolResult.fail("policy", f"{decision.reason} — drafting not permitted "
                                             f"at this approval level")

        draft = draft_reply(msg, memory=None, tone=str(p.get("tone") or ""))
        draft.status = "needs_approval"
        store.store_draft(draft)
        local_mark = " (locally generated — no provider)" if draft.generated_locally else ""
        return ToolResult.ok(
            data={"draft_id": draft.draft_id, "risk": list(draft.risk_markers)},
            message=f"Draft {draft.draft_id} prepared{local_mark} — to "
                    f"{draft.recipient} on {draft.platform}. Risk markers: "
                    f"{', '.join(draft.risk_markers) or 'none'}. "
                    f"Review, then send with comm_send.")


class CommSendTool(Tool):
    name = "comm_send"
    description = ("Send a prepared draft after review. Confirmation is "
                   "required (destructive): confirmation runs policy check, "
                   "pre-send verification, anti-spam rails, connector send, "
                   "platform verification, audit log and learning.")
    parameters = {"draft_id": "the draft to send"}
    destructive = True

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        from comms import store
        from comms.engine import send_draft
        from comms.models import Draft

        draft_id = str((parameters or {}).get("draft_id") or "")
        row = store.get_draft(draft_id)
        if row is None:
            return ToolResult.fail("not_found", f"no draft with id {draft_id!r}")
        if row["status"] in ("sent",):
            return ToolResult.fail("already_sent", f"draft {draft_id} was already sent")
        draft = Draft(platform=row["platform"], recipient=row["recipient"],
                      body=row["body"], subject=row.get("subject", ""),
                      conversation_id=row.get("conversation_id", ""),
                      account=row.get("account", ""), tone=row.get("tone", "casual"),
                      generated_locally=bool(row.get("generated_locally")),
                      checks=row.get("checks") or {},
                      risk_markers=tuple(row.get("risk_markers") or ()),
                      draft_id=row["draft_id"])
        # reaching here means the human confirmed (tool confirmation flow);
        # policy/rails/checks still run inside send_draft — confirmation
        # NEVER bypasses them
        result = send_draft(draft, confirmed=True)
        if result["ok"]:
            return ToolResult.ok(data=result["report"],
                                 message=f"Sent via {draft.platform}. "
                                         f"Verification: {result.get('verification', '')}")
        return ToolResult.fail(result.get("status", "failed"),
                               result.get("platform_result")
                               or result.get("error")
                               or result.get("report", {}).get("reason", "send failed")
                               or "send failed")


class CommHealthTool(Tool):
    name = "comm_health"
    description = "Report connector health: state per platform + policy levels + pending counts."
    parameters = {}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        from comms import store
        from comms.inbox import overview
        from comms.registry import connectors
        health = connectors.health()
        lines = []
        if not health:
            lines.append("No connectors configured (set EMAIL_*/TELEGRAM_BOT_TOKEN "
                         "or Termux notification access to enable platforms).")
        for platform, h in sorted(health.items()):
            lines.append(f"- {platform}: {h['state']}"
                         + (f" — {h['detail']}" if h.get("detail") else ""))
        counts = overview()
        lines.append(f"inbox: {counts['total']} message(s); "
                     f"drafts pending: {counts['pending_drafts']}; "
                     f"urgent: {counts['urgent']}")
        return ToolResult.ok(data={"connectors": health, "counts": counts},
                             message="\n".join(lines))


class ContactLookupTool(Tool):
    name = "contact_lookup"
    description = ("Look up a person in the authorized contact book (and the "
                   "device address book when Termux:API allows). Never exposes "
                   "more than name, identifiers and stored communication context.")
    parameters = {"name": "name / number / handle to find"}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        from comms.contacts import lookup
        query = str((parameters or {}).get("name") or "")
        contact = lookup(query)
        if contact is None:
            return ToolResult.ok(message=f"No contact found for '{query}'.")
        ids = ", ".join(str(i) for i in contact.get("identifiers", [])) or "—"
        return ToolResult.ok(
            data={"name": contact["name"], "identifiers": contact.get("identifiers", [])},
            message=f"{contact['name']} — identifiers: {ids}; "
                    f"platforms: {', '.join(contact.get('platforms') or []) or '—'}; "
                    f"last topic: {contact.get('last_topic') or '—'}")


class CalendarListTool(Tool):
    name = "calendar_list"
    description = "List upcoming calendar events (local authorized calendar). Optional days window."
    parameters = {"days": "optional int (default 7)"}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        from comms import calendar
        days = int((parameters or {}).get("days") or 7)
        events = calendar.upcoming(days)
        if not events:
            return ToolResult.ok(message=f"No events in the next {days} day(s).")
        lines = [f"- {time.strftime('%Y-%m-%d %H:%M', time.localtime(e['start']))} "
                 f"{e['title']} ({int((e['end']-e['start'])//60)}m)" for e in events]
        return ToolResult.ok(data={"count": len(events)}, message="\n".join(lines))


class CalendarAddTool(Tool):
    name = "calendar_add"
    description = ("Create a calendar event. Destructive (modifies the user's "
                   "calendar): confirmation is required first.")
    parameters = {"title": "event title",
                  "start_ts": "unix timestamp for start",
                  "duration_min": "optional minutes (default 60)",
                  "notes": "optional"}
    destructive = True

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        from comms import calendar
        p = parameters or {}
        title = str(p.get("title") or "").strip()
        try:
            start = float(p.get("start_ts") or 0)
        except (TypeError, ValueError):
            return ToolResult.fail("invalid_parameter", "start_ts must be a unix timestamp")
        duration = int(p.get("duration_min") or 60)
        res = calendar.create(title, start, duration, notes=str(p.get("notes", "")))
        if not res["ok"]:
            return ToolResult.fail("invalid", res["reason"])
        clash = f" Conflicts with: {', '.join(res['conflicts'])}." if res["conflicts"] else ""
        return ToolResult.ok(data=res,
                             message=f"Event '{title}' created ({res['event_id']}).{clash}")


class WorkflowListTool(Tool):
    name = "workflow_list"
    description = "List configured communication workflows and their recent runs."
    parameters = {}

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        from comms import store
        wfs = store.list_workflows()
        if not wfs:
            return ToolResult.ok(message="No workflows defined yet (define one with workflow_run's definition parameter or the UI).")
        lines = []
        for w in wfs:
            trig = (w["definition"].get("trigger") or {}).get("type", "?")
            lines.append(f"- {w['name']} [{w['workflow_id']}] trigger={trig} "
                         f"enabled={bool(w['enabled'])}")
        runs = store.recent_runs(limit=5)
        if runs:
            lines.append("recent runs: " + "; ".join(
                f"{r['workflow_id']}:{'ok' if r['success'] else 'FAIL'}" for r in runs))
        return ToolResult.ok(message="\n".join(lines))


class WorkflowRunTool(Tool):
    name = "workflow_run"
    description = ("Manually run or define+run a workflow. Parameters: "
                   "definition (dict with trigger+steps) to save and execute, "
                   "or workflow_id to re-run an existing one against a manual "
                   "event. Creating automation is destructive (confirmation "
                   "required); running read-only steps is not.")
    parameters = {"definition": "optional workflow definition dict",
                  "name": "name when defining", "workflow_id": "existing id",
                  "event_summary": "text summary for a manual trigger event"}
    destructive = True

    def available(self) -> bool:
        return True

    def execute(self, parameters: dict) -> ToolResult:
        from comms import store
        from comms.workflow import engine
        p = parameters or {}
        definition = p.get("definition")
        wf_id = str(p.get("workflow_id") or "")
        if isinstance(definition, str):
            try:
                definition = json.loads(definition)
            except Exception:
                return ToolResult.fail("invalid_parameter", "definition must be a JSON object")
        if definition:
            if not isinstance(definition, dict) or not definition.get("steps"):
                return ToolResult.fail("invalid_parameter",
                                       "definition needs a 'steps' list (and optional trigger)")
            wf_id = wf_id or str(int(time.time()))
            store.save_workflow(wf_id, str(p.get("name") or definition.get("name", wf_id)),
                                definition)
        elif wf_id:
            found = [w for w in store.list_workflows() if w["workflow_id"] == wf_id]
            if not found:
                return ToolResult.fail("not_found", f"no workflow {wf_id!r}")
            definition = found[0]["definition"]
        else:
            return ToolResult.fail("missing_parameter",
                                   "give a definition or an existing workflow_id")
        result = engine.run(definition,
                            {"type": "command",
                             "summary": str(p.get("event_summary") or "manual run")},
                           workflow_id=wf_id or definition.get("id", "adhoc"))
        marks = "; ".join(f"{s['name']}={s['outcome']}" for s in result["steps"])
        return ToolResult.ok(data=result,
                             message=f"workflow {'succeeded' if result['success'] else 'failed'}: "
                                     f"{marks or 'no steps'}") if result["success"] else \
               ToolResult.fail("workflow_failed", f"{marks}. error: {result['error']}")
