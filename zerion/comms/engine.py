# comms/engine.py
"""The send pipeline — the ONLY way an outbound item leaves Zerion.

    draft → POLICY (approvals.decide)
          → PRE-SEND CHECKLIST (verify.pre_send_checklist)
          → RATE RAILS (ratelimit.check)
          → CONNECTOR.send
          → VERIFY PLATFORM RESULT
          → AUDIT + LEDGER + MEMORY + (failure → error memory)

"mode" expresses WHERE the human decision happened:
  "check"   — dry run: decision + checklist + rails only, nothing sent
  "submit"  — the caller has collected explicit user confirmation already
              (UI approve button / chat 'confirm'); only valid when the
              decision was "confirm" and confirmed=True
  "auto"    — trusted rules; only the policy engine may decide this
"""

from __future__ import annotations

import time

from comms import approvals, audit, ratelimit, store, verify
from comms.registry import connectors
from core import logging as log


def evaluate_send(draft, decision: approvals.PolicyDecision | None = None,
                  workflow: str = "") -> dict:
    """Full pre-flight without sending. Returns the honest gate report."""
    if decision is None:
        decision = approvals.decide(draft.platform, draft.account,
                                    draft.recipient, draft.body,
                                    workflow=workflow)
    checks = verify.pre_send_checklist(
        draft,
        connector_lookup=connectors.get,
        inbox_lookup=lambda cid: store.conversation_history(cid, limit=1))
    rail = ratelimit.check(draft.platform, draft.recipient, draft.body)
    report = {
        "action": decision.action, "reason": decision.reason,
        "risk": list(decision.risk), "effective_level": decision.effective_level,
        "checks": checks, "checks_pass": verify.checks_pass(checks),
        "rail": {"allowed": rail.allowed, "reason": rail.reason},
    }
    return report


def send_draft(draft, confirmed: bool = False, workflow: str = "",
               agent: str = "") -> dict:
    """Attempt to send. Never bypasses a gate; every outcome is auditable."""
    started = time.time()
    decision = approvals.decide(draft.platform, draft.account,
                                draft.recipient, draft.body, workflow=workflow)
    report = evaluate_send(draft, decision, workflow)

    def _finish(status: str, result: dict, error: str = "") -> dict:
        verification = ""
        if result:
            ok, verification = verify.verify_platform_result(result)
        store.set_draft_status(draft.draft_id, status)
        audit.record("send", draft.platform, account=draft.account,
                     target=draft.recipient, workflow=workflow, agent=agent,
                     permission_level=decision.effective_level,
                     result=result.get("platform_result", "") if result else "",
                     error=error, verification=verification,
                     extra={"draft_id": draft.draft_id,
                            "generated_locally": draft.generated_locally,
                            "checks": report["checks"], "rail": report["rail"],
                            "ms": int((time.time() - started) * 1000)})
        return {"ok": status == "sent", "status": status, "error": error,
                "report": report, "platform_result": result.get("platform_result", "") if result else "",
                "verification": verification}

    if decision.action == "deny":
        return _finish("failed", {}, error=decision.reason)
    if decision.action in ("observe", "draft"):
        return _finish("needs_approval", {}, error=decision.reason)
    if decision.action == "confirm" and not confirmed:
        return _finish("needs_approval", {}, error=decision.reason)
    if not report["checks_pass"]:
        failed = [k for k, v in report["checks"].items() if not v]
        return _finish("failed", {}, error="pre-send checklist failed: " + ", ".join(failed))
    if not report["rail"]["allowed"]:
        return _finish("failed", {}, error="rate rail: " + report["rail"]["reason"])

    connector = connectors.get(draft.platform)
    if connector is None:
        return _finish("failed", {}, error=f"no active connector for '{draft.platform}'")
    if not connector.supports("send"):
        # read-only platform: surface the connector's own reason (e.g. the
        # supervised deep-link flow for social apps), not a bare check name
        return _finish("failed", connector.send(draft),
                       error="platform does not support programmatic send")

    result = connector.send(draft)
    ok, note = verify.verify_platform_result(result)
    if ok:
        ratelimit.record(draft.platform, draft.recipient, draft.body,
                         draft.draft_id, note)
        _remember_success(draft)
        return _finish("sent", result)
    _remember_failure(draft, note)
    return _finish("failed", result, error=note)


def _remember_success(draft) -> None:
    """Useful-pattern learning only (never raw bodies): tone+platform
    outcome. Per mission 31: store patterns, not conversations."""
    try:
        from knowledge.manager import KnowledgeManager
        KnowledgeManager().store(
            f"communication pattern: {draft.platform}/{draft.tone} reply accepted",
            "comm_pattern", [draft.platform, draft.tone], .5, .7,
            {"platform": draft.platform, "tone": draft.tone,
             "generated_locally": draft.generated_locally},
            layer="capability")
        if draft.recipient:
            store.contact_note(draft.recipient, f"sent {draft.platform} reply")
    except Exception as e:
        log.debug(f"comm learn (success) deferred: {e}")


def _remember_failure(draft, reason: str) -> None:
    try:
        from learning.errors import ErrorMemory
        ErrorMemory().record(
            f"send {draft.platform} message to {draft.recipient}",
            f"draft {draft.draft_id} ({draft.tone})",
            str(reason), "unknown",
            "inspect platform result, adjust content or timing", "")
    except Exception as e:
        log.debug(f"comm learn (failure) deferred: {e}")
