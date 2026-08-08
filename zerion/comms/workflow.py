# comms/workflow.py
"""Adaptive workflow engine — TRIGGER → UNDERSTAND → DECIDE → ACT → VERIFY → LEARN.

A workflow definition is DATA (stored in comm_workflows), not code:

  {"trigger": {"type": "email.new" | "telegram.new" | "notification.new" |
                "calendar.soon" | "schedule" | "command" | "event",
               "match": {field: value, ...}},
   "steps": [
      {"action": "...", "params": {...},
       "when": [{field ops value}...],          # optional gate
       "on_fail": {"action": "...", "params": {...}}  # optional alternative
   }]}

Adaptive (mission §23): every step conditionally evaluates against the live
context; a failed step takes its on_fail branch; the engine observes results
between steps instead of marching blindly A→B→C.

Learning (mission §24): successful runs record a workflow_pattern into the
knowledge layer; failures record structured error memory with cause; both
are strictly pattern-level (no message bodies in learning).

Execution sandbox: actions map to the EXISTING systems only — tool_manager
(same Constitution+confirmation), agent pool (whitelisted), comms engine
(same policy/rails), calendar store, notifications. The engine adds nothing
new outside those permissions.
"""

from __future__ import annotations

import time
import uuid

from comms import audit, store
from core import logging as log

# trigger types → how the scheduler reaches them (comms/scheduler.py)
TRIGGER_TYPES = ("email.new", "telegram.new", "notification.new",
                 "calendar.soon", "schedule", "command", "event")

_OPS = ("eq", "ne", "contains", "in", "gte", "lte", "exists")


def _resolve(path: str, ctx: dict):
    node = ctx
    for part in str(path).split("."):
        if isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    return node


def eval_condition(cond: dict, ctx: dict) -> bool:
    field, op, value = cond.get("field"), cond.get("op", "eq"), cond.get("value")
    actual = _resolve(field, ctx)
    if op == "exists":
        return actual is not None
    if actual is None:
        return False
    if op == "eq":
        return actual == value
    if op == "ne":
        return actual != value
    if op == "contains":
        return str(value).lower() in str(actual).lower()
    if op == "in":
        return actual in (value if isinstance(value, (list, tuple)) else [value])
    if op == "gte":
        try:
            return float(actual) >= float(value)
        except Exception:
            return False
    if op == "lte":
        try:
            return float(actual) <= float(value)
        except Exception:
            return False
    return False


class WorkflowEngine:
    def run(self, definition: dict, event: dict, workflow_id: str = "") -> dict:
        wid = workflow_id or definition.get("id") or uuid.uuid4().hex[:8]
        run_id = uuid.uuid4().hex[:10]
        started = time.time()
        trigger_summary = str(event.get("summary") or event.get("type", ""))[:160]
        ctx = {"event": event, "results": {}}
        steps_report = []
        success = True
        error = ""

        for i, step in enumerate(definition.get("steps") or []):
            name = f"step{i}:{step.get('action', '?')}"
            # adaptive gate: observe first, decide whether this step applies
            gates = step.get("when") or []
            if gates and not all(eval_condition(c, ctx) for c in gates):
                steps_report.append({"name": name, "outcome": "skipped-condition"})
                continue
            try:
                outcome = self._act(step.get("action"), step.get("params") or {}, ctx)
                steps_report.append({"name": name, "outcome": outcome.get("status", "done"),
                                     "detail": str(outcome.get("detail", ""))[:160]})
                ctx["results"][name] = outcome
                if outcome.get("status") == "failed":
                    alt = step.get("on_fail")
                    if alt:
                        alt_outcome = self._act(alt.get("action"), alt.get("params") or {}, ctx)
                        steps_report.append({"name": f"{name}.on_fail",
                                             "outcome": alt_outcome.get("status", "done"),
                                             "detail": str(alt_outcome.get("detail", ""))[:160]})
                        if alt_outcome.get("status") == "failed":
                            success = False
                            error = f"step {i} and its fallback failed"
                            break
                    else:
                        success = False
                        error = f"step {i} failed: {outcome.get('detail', '')[:120]}"
                        break
            except Exception as e:
                success = False
                error = f"step {i} raised: {type(e).__name__}: {e}"[:160]
                steps_report.append({"name": name, "outcome": "error", "detail": error})
                break

        store.record_run(wid, run_id, trigger_summary, steps_report,
                         success, started, error)
        self._learn(wid, definition, success, error, steps_report)
        audit.record("workflow_run", platform="workflow",
                     workflow=definition.get("name", wid),
                     result="success" if success else "failed", error=error)
        return {"run_id": run_id, "workflow_id": wid, "success": success,
                "steps": steps_report, "error": error,
                "duration_ms": int((time.time() - started) * 1000)}

    # -- actions (each maps onto an EXISTING, permission-gated system) ------

    def _act(self, action: str, params: dict, ctx: dict) -> dict:
        event = ctx.get("event", {})

        if action == "classify":
            # UNDERSTAND: classify the inbound item and stash it in context
            from comms.classify import classify_message
            from comms.models import UnifiedMessage
            m = event.get("message")
            if isinstance(m, UnifiedMessage):
                classify_message(m)
            ctx.setdefault("understanding", {})[str(event.get("id", "event"))] = \
                getattr(m, "classification", None) or "unknown"
            return {"status": "done", "detail": getattr(m, "classification", "unknown")}

        if action == "store_inbox":
            from comms.inbox import ingest
            msg = event.get("message")
            if msg is None:
                return {"status": "failed", "detail": "trigger carried no message"}
            return {"status": "done", "detail": str(ingest(msg))[:160]}

        if action == "draft_reply":
            from comms.reply import draft_reply
            from comms.models import UnifiedMessage
            msg = event.get("message")
            if not isinstance(msg, UnifiedMessage):
                return {"status": "failed", "detail": "no message to answer"}
            draft = draft_reply(msg, memory=None, tone=str(params.get("tone", "")))
            store.store_draft(draft)
            ctx["draft"] = draft
            return {"status": "done", "detail": f"draft {draft.draft_id} prepared",
                    "draft_id": draft.draft_id}

        if action == "send_reply":
            # armed=false is zero-confirmation context for scheduler runs;
            # sends from here need trusted rules or they park as approvals
            from comms.engine import send_draft
            draft = ctx.get("draft")
            if draft is None:
                draft_id = params.get("draft_id")
                row = store.get_draft(str(draft_id)) if draft_id else None
                if row is None:
                    return {"status": "failed", "detail": "no draft prepared"}
                from comms.models import Draft
                draft = Draft(platform=row["platform"], recipient=row["recipient"],
                              body=row["body"], subject=row["subject"],
                              conversation_id=row["conversation_id"],
                              account=row["account"], tone=row["tone"],
                              draft_id=row["draft_id"])
            result = send_draft(draft, confirmed=bool(params.get("confirmed", False)),
                                workflow=ctx.get("workflow_name", ""))
            return {"status": "done" if result["ok"] else "failed",
                    "detail": result.get("status", "") or result.get("platform_result", "")}

        if action == "notify_user":
            text = str(params.get("text") or event.get("summary") or "Zerion notification")
            ok = False
            try:
                from phone.adapter import TermuxAdapter
                ok = TermuxAdapter().run("termux-notification", "--title", "Zerion",
                                         "--content", text[:300]).success
            except Exception:
                ok = False
            if not ok:
                log.info(f"notify_user (no device notification channel): {text[:120]}")
            return {"status": "done", "detail": f"notification {'shown' if ok else 'logged'}"}

        if action == "create_event":
            from comms import calendar
            title = str(params.get("title") or f"Follow-up: {event.get('summary', 'message')[:60]}")
            when = float(params.get("start_ts") or (time.time() + 3600 * int(params.get("in_hours", 24))))
            res = calendar.create(title, when, int(params.get("duration_min", 30)))
            return {"status": "done" if res["ok"] else "failed",
                    "detail": str({k: v for k, v in res.items() if k != "notes"})[:160]}

        if action == "run_tool":
            from tools.manager import tool_manager
            name = str(params.get("tool", ""))
            result = tool_manager.execute(name, params.get("parameters") or {})
            return {"status": "done" if result.success else "failed",
                    "detail": result.message[:160]}

        if action == "call_agent":
            from agents.service import pool
            result = pool.spawn(str(params.get("type", "researcher")),
                                {"query": str(params.get("query") or event.get("summary", ""))[:200]},
                                wait=True)
            agent = result.get("agent") or {}
            return {"status": "done" if result.get("ok") and agent.get("status") == "completed"
                    else "failed",
                    "detail": str((agent.get("result") or {}).get("message", ""))[:160]}

        if action == "store_memory":
            from knowledge.manager import KnowledgeManager
            content = str(params.get("content") or event.get("summary", ""))[:300]
            if not content:
                return {"status": "failed", "detail": "nothing to store"}
            KnowledgeManager().store(content, str(params.get("category", "workflow_note")),
                                     [str(params.get("tag", "workflow"))], .5, .6,
                                     {"workflow": ctx.get("workflow_name", "")},
                                     layer="knowledge")
            return {"status": "done", "detail": "stored"}

        if action == "log":
            log.info(f"workflow log: {str(params.get('text',''))[:160]}")
            return {"status": "done", "detail": "logged"}

        return {"status": "failed", "detail": f"unknown action {action!r}"}

    # -- bounded learning ----------------------------------------------------

    def _learn(self, wid: str, definition: dict, success: bool,
               error: str, steps: list) -> None:
        try:
            if success:
                from knowledge.manager import KnowledgeManager
                KnowledgeManager().store(
                    f"workflow pattern: {definition.get('name', wid)} succeeded "
                    f"({len(steps)} steps)",
                    "workflow_pattern", [wid, "success"], .6, .8,
                    {"workflow_id": wid, "trigger": (definition.get("trigger") or {}).get("type"),
                     "steps": [s["name"] for s in steps]},
                    layer="capability")
            else:
                from learning.errors import ErrorMemory
                ErrorMemory().record(
                    f"workflow {definition.get('name', wid)}",
                    f"trigger {(definition.get('trigger') or {}).get('type', '?')}",
                    error or "unknown failure", "unknown",
                    "inspect the failing step and its on_fail branch", "")
        except Exception as e:
            log.debug(f"workflow learn deferred: {e}")


engine = WorkflowEngine()
