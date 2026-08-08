# phone/actions.py
"""The Phone Action model: every phone interaction is ONE structured record
with a complete lifecycle. The UI/API never sends raw commands — it only
creates or approves these records, so authorization gates can't be dodged
by a differently-shaped request."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict


# risk tiers decide which gate applies — consequential actions require an
# explicit human approval step through the existing dispatcher/constitution
RISK_READ_ONLY = "read_only"        # state probes (no phone effect)
RISK_CONSEQUENTIAL = "consequential"  # any device-visible effect


# approval lifecycle
APPROVAL_NOT_REQUIRED = "not_required"
APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_DENIED = "denied"
APPROVAL_TIMEOUT = "timeout"

# execution lifecycle
EXEC_QUEUED = "queued"
EXEC_EXECUTING = "executing"
EXEC_EXECUTED = "executed"
EXEC_FAILED = "failed"
EXEC_SKIPPED = "skipped"

# verification states — the honesty contract
VERIFY_NOT_CHECKED = "unverified"
VERIFY_SUCCESS = "verified_success"
VERIFY_FAILURE = "verified_failure"
VERIFY_UNVERIFIABLE = "execution_unverified"   # the platform gives no readback


@dataclass
class PhoneAction:
    capability: str
    parameters: dict = field(default_factory=dict)
    reason: str = ""
    requested_by: str = "user"
    risk_level: str = RISK_CONSEQUENTIAL
    expected: str = ""
    action_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    created_at: float = field(default_factory=time.time)
    approval_state: str = APPROVAL_NOT_REQUIRED
    execution_state: str = EXEC_QUEUED
    verification: str = VERIFY_NOT_CHECKED
    result_message: str = ""
    result_data: str = ""
    attempts: int = 0
    finished_at: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# failure classification → determines retry policy (never blind repeats)
FAIL_TRANSIENT = "transient"      # timeouts, transient IO: may retry once
FAIL_PERMISSION = "permission"    # Android denied: never auto-retry
FAIL_MISSING_BINARY = "missing_binary"  # termux tool absent: never retry
FAIL_UNSUPPORTED = "unsupported"  # capability absent
FAIL_LOGICAL = "logical"          # nonzero exit / refused


def classify_failure(message: str) -> str:
    m = (message or "").lower()
    if "securityexception" in m or "permission denied" in m or "not authorized" in m:
        return FAIL_PERMISSION
    if "unavailable" in m or "no such file" in m or "not found" in m or "command not found" in m:
        return FAIL_MISSING_BINARY
    if "timeout" in m or "timed out" in m or "temporarily" in m or "connection" in m:
        return FAIL_TRANSIENT
    return FAIL_LOGICAL


def retry_allowed_after(failure_kind: str, risk_level: str, attempts: int) -> bool:
    """Conservative: at most one retry; only for transient failures; the
    RETRY ITSELF is consequential-gated (same gate as the first attempt)."""
    if attempts >= 2:
        return False
    if risk_level != RISK_READ_ONLY and failure_kind != FAIL_TRANSIENT:
        return False
    return failure_kind == FAIL_TRANSIENT
