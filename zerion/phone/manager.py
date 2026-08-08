# phone/manager.py
"""PhoneBodyManager — Zerion's physical body orchestrator.

Owns the complete action lifecycle:

    intent/request
      ↓
    capability present?    (discovery)
      ↓
    PhoneAction record     (structured, never raw)
      ↓
    Constitution gate      (policy.evaluate — unchanged, upstream)
      ↓
    approval gate          (existing pending-approval flow — unchanged)
      ↓
    execution              (existing PhoneDispatcher — NOT reimplemented)
      ↓
    failure classification (transient-only retry, never blind repeats)
      ↓
    honest verification    (verified_success / verified_failure /
                            execution_unverified — never fake success)
      ↓
    state refresh + audit  (PhoneState + append-only JSONL trail)

.billing contracts:
- dispatch(goal, intent, approved=False) is a DROP-IN richer replacement for
  PhoneDispatcher.dispatch — same call shape, same ActionResult message
  contract. Everything else the manager adds stays *inside* it.
- UI/API never executes directly: they only create/approve PhoneAction
  records through this manager.
"""

from __future__ import annotations

import os
import time

from constitution import Constitution
from phone.actions import (
    PhoneAction, RISK_READ_ONLY,
    APPROVAL_NOT_REQUIRED, APPROVAL_PENDING, APPROVAL_APPROVED,
    EXEC_QUEUED, EXEC_EXECUTING, EXEC_EXECUTED, EXEC_FAILED,
    VERIFY_UNVERIFIABLE, VERIFY_SUCCESS, VERIFY_FAILURE,
    retry_allowed_after, classify_failure,
)
from phone.audit import PhoneAuditLog
from phone.dispatch import PhoneDispatcher
from phone.discovery import CapabilityDiscovery
from phone.extract import PhoneIntent
from phone.models import ActionResult
from phone.state import PhoneState
from phone.verifier import ExecutionVerifier


def _audit_path() -> str:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "runtime", "run", "phone_audit.jsonl")


# capabilities that can VERIFY by re-reading state afterward
_RE_READABLE = frozenset()   # nothing is reliably re-readable via Termux API


class PhoneBodyManager:
    """Zerion's first-class physical body. One per process (built by
    PhoneIntelligence so the phone package's entry point composes the Core
    exactly like before; ui.session flips one attribute to drive it)."""

    def __init__(self, dispatcher: PhoneDispatcher, discovery: CapabilityDiscovery,
                 constitution: Constitution | None = None):
        self.dispatcher = dispatcher
        self.discovery = discovery
        self.constitution = constitution or dispatcher.constitution
        self.state = PhoneState(discovery, adapter=getattr(dispatcher, "adapter", None))
        self.audit = PhoneAuditLog(_audit_path())
        self._actions: dict[str, PhoneAction] = {}
        self._pending: dict[str, tuple[str, object]] = {}  # action_id → (goal, intent)

    # ------------------------------------------------------------------
    # state surface (the self-aware device model)
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        return self.state.snapshot()

    def what_can_i_do(self) -> list[tuple[str, str]]:
        return self.state.what_can_i_do()

    def what_cant_i_do(self) -> list[str]:
        return self.state.what_cant_i_do()

    def what_permissions(self) -> dict:
        return self.state.what_permissions()

    def device_state(self) -> dict:
        return self.state.device_state()

    def current_action(self) -> dict | None:
        return self.state.current_action_desc()

    def action(self, action_id: str) -> dict | None:
        a = self._actions.get(action_id)
        return a.to_dict() if a else None

    def recent_actions(self, limit: int = 25) -> list[dict]:
        return [a.to_dict() for a in
                sorted(self._actions.values(), key=lambda a: a.created_at)[-limit:]]

    # ------------------------------------------------------------------
    # dispatch — DROP-IN richer replacement for PhoneDispatcher.dispatch
    # ------------------------------------------------------------------

    def dispatch(self, goal: str, intent: PhoneIntent | None, approved: bool = False):
        """Same signature as PhoneDispatcher.dispatch. All paths from
        main.py land in the same safe place either way; the UI session uses
        this manager. Returns ActionResult (compat) while recording the
        complete lifecycle internally."""
        if intent is None:
            return ActionResult(False, "No phone action recognized.")
        if getattr(intent, "missing", None):
            return ActionResult(False, "Missing required information: "
                                + ", ".join(intent.missing) + ".")

        action = PhoneAction(
            capability=intent.capability,
            parameters=dict(intent.parameters),
            reason=goal,
            requested_by="conversation",
            risk_level=("consequential" if intent.capability in
                        {"clipboard_write", "torch", "telephony", "sms", "camera",
                         "open_url", "notification", "media", "volume"}
                        else RISK_READ_ONLY),
        )
        self._actions[action.action_id] = action
        self.audit.record({"event": "action.created", "action": action.to_dict()})

        # capability present?
        if not self._capability_available(action.capability):
            action.execution_state = EXEC_FAILED
            action.finished_at = time.time()
            action.result_message = (f"Capability '{action.capability}' is not available "
                                     f"on this device (Termux API binary missing).")
            self.state.note_denied(action.capability, action.result_message)
            self.audit.record({"event": "action.unavailable",
                               "action_id": action.action_id,
                               "capability": action.capability})
            return ActionResult(False, action.result_message)

        # constitution gate — same evaluation rule as PhoneDispatcher
        consequential = action.risk_level != RISK_READ_ONLY
        decision = self.constitution.evaluate(
            "execute_shell" if consequential else "reason")
        if not decision.allowed:
            action.approval_state = "policy_denied"
            action.execution_state = EXEC_FAILED
            action.result_message = decision.reason
            action.finished_at = time.time()
            self.state.note_denied(action.capability, decision.reason)
            self.audit.record({"event": "action.policy_denied",
                               "action_id": action.action_id, "reason": decision.reason})
            return ActionResult(False, decision.reason)

        # approval gate — unchanged semantic from PhoneDispatcher
        if consequential and not approved:
            action.approval_state = APPROVAL_PENDING
            self._pending[action.action_id] = (goal, intent)
            self.audit.record({"event": "action.pending_approval",
                               "action_id": action.action_id})
            return ActionResult(False,
                                f"Approval required for {intent.capability}.")

        action.approval_state = (APPROVAL_APPROVED if consequential else APPROVAL_NOT_REQUIRED)
        return self._execute(action, goal, intent)

    # ------------------------------------------------------------------
    # execution + honest verification + recovery
    # ------------------------------------------------------------------

    def _execute(self, action: PhoneAction, goal: str, intent: PhoneIntent) -> ActionResult:
        action.execution_state = EXEC_EXECUTING
        action.attempts += 1
        self.state.note_action_started(action.action_id)

        # delegate the actual operation to the EXISTING dispatcher — never
        # a second control path
        result = self.dispatcher.dispatch(goal, intent, approved=True)
        action.result_message = result.message
        action.result_data = result.data or ""

        if result.success:
            action.execution_state = EXEC_EXECUTED
            verification = self._verify(action, intent)
            action.verification = verification
            action.finished_at = time.time()
            self.state.note_action_finished(action.capability, verification)
            self.state.refresh(force=True)
            self.audit.record({"event": "action.executed",
                               "action_id": action.action_id,
                               "verification": verification})
            # compat: message text unchanged (main.py prints it)
            message = result.message
            if verification == VERIFY_UNVERIFIABLE:
                message += " (execution unverified)"
            return ActionResult(True, message, result.data, verified=(verification == VERIFY_SUCCESS))

        # failure → classify → maybe one bounded retry for transients only
        kind = classify_failure(result.message)
        self.audit.record({"event": "action.failed", "action_id": action.action_id,
                           "kind": kind, "message": result.message[:200]})

        if retry_allowed_after(kind, action.risk_level, action.attempts):
            self.audit.record({"event": "action.retry", "action_id": action.action_id,
                               "kind": kind})
            action.attempts += 1
            retry = PhoneDispatcher(
                self.dispatcher.controllers,
                getattr(self.dispatcher, "verifier", None) or ExecutionVerifier(),
                self.dispatcher.constitution,
            ).dispatch(goal, intent, approved=True)
            if retry.success:
                action.execution_state = EXEC_EXECUTED
                verification = self._verify(action, intent)
                action.verification = verification
                action.finished_at = time.time()
                self.state.note_action_finished(action.capability, verification)
                self.audit.record({"event": "action.recovered", "action_id": action.action_id})
                return ActionResult(True, retry.message, retry.data,
                                    verified=(verification == VERIFY_SUCCESS))
            result = retry
            kind = classify_failure(retry.message) if not retry.success else kind

        action.execution_state = EXEC_FAILED
        action.verification = VERIFY_FAILURE
        action.finished_at = time.time()
        self.state.note_action_finished(action.capability, VERIFY_FAILURE)
        self.state.refresh(force=True)
        self.audit.record({"event": "action.terminal_failure", "action_id": action.action_id,
                           "kind": kind})
        if kind == "permission":
            self.state.note_denied(action.capability, result.message)
        return ActionResult(False, result.message, result.data, verified=False)

    def _verify(self, action: PhoneAction, intent) -> str:
        """verified_success only comes from state readback; when the platform
        gives no readback (Termux fires-and-forgets), we are HONEST:
        execution_unverified. No binary-level check is faked."""
        cap = action.capability
        if cap in _RE_READABLE:
            # kept for future readback-capable caps
            probe = self.dispatcher.controllers.get(cap)
            try:
                check = getattr(probe, "read", None) or getattr(probe, "readback", None)
                if callable(check):
                    obs = check()
                    return VERIFY_SUCCESS if getattr(obs, "success", False) else VERIFY_FAILURE
            except Exception:
                pass
        return VERIFY_UNVERIFIABLE

    # ------------------------------------------------------------------

    def _capability_available(self, name: str) -> bool:
        try:
            for c in self.discovery.capabilities():
                if c.name == name:
                    return bool(c.available)
        except Exception:
            return False
        return False

    def pending_approvals(self) -> list[dict]:
        return [self._actions[aid].to_dict() for aid in self._pending
                if aid in self._actions]

    def approve_pending(self, action_id: str) -> ActionResult | None:
        """Approve and execute a parked action. Called by the session's
        existing confirmation flow — the approval semantics never change."""
        entry = self._pending.pop(action_id, None)
        if entry is None:
            return None
        goal, intent = entry
        a = self._actions[action_id]
        a.approval_state = APPROVAL_APPROVED
        return self._execute(a, goal, intent)

    def deny_pending(self, action_id: str) -> None:
        self._pending.pop(action_id, None)
        a = self._actions.get(action_id)
        if a:
            a.approval_state = "denied"
            a.execution_state = EXEC_SKIPPED
            a.finished_at = time.time()
            self.audit.record({"event": "action.denied", "action_id": action_id})
