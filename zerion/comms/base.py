# comms/base.py
"""Connector contract: CONNECTOR → AUTH → CAPABILITY DISCOVERY → UNIFIED
INTERFACE → ZERION.

A connector wraps ONE authorized account/protocol. It never bypasses the
Core (no direct filesystem/Android/network tricks beyond its own protocol
client), never stores secrets, and reports honest health. Everything it
returns is normalized to UnifiedMessage; everything it sends is a Draft
that already passed approvals/policy/rate-limit/verification upstream.

Health states (reported, never asserted):
    disconnected  — not configured / credentials absent
    error         — configured but the last probe failed
    degraded      — partially working (e.g. read ok, write forbidden)
    connected     — transport reachable
    authenticated — credentials verified by the platform
    available     — authenticated + send capability confirmed where permitted
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from comms.models import UnifiedMessage, Draft

ALL_CAPABILITIES = frozenset({
    "read", "search", "create", "update", "send", "delete", "events",
    "contacts", "calendar",
})

HEALTH_STATES = frozenset({
    "disconnected", "error", "degraded", "connected", "authenticated", "available",
})


class Connector(ABC):
    name: str = ""
    platform: str = ""
    capabilities: frozenset = frozenset()

    @abstractmethod
    def configured(self) -> bool:
        """True only when the connector has what it needs to try live work.
        Must never read disk or network — config presence only."""

    @abstractmethod
    def health(self) -> dict:
        """Returns {"state": one of HEALTH_STATES, "detail": str}. Must be
        cheap, must never raise, must never fabricate availability."""

    def read(self, limit: int = 20) -> list:
        """Newest messages as UnifiedMessage list (normalized)."""
        return []

    def search(self, query: str, limit: int = 20) -> list:
        return []

    def poll_events(self) -> list:
        """New inbound items since the connector's own cursor. Empty when
        nothing new or events unsupported."""
        return []

    def send(self, draft: Draft) -> dict:
        """Perform the platform send. Returns {"ok": bool, "platform_result": ...}.
        Connectors must refuse drafts whose platform mismatches."""
        return {"ok": False, "platform_result": "send not supported"}

    # -- capability passthroughs (only where the platform actually has them)
    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    def archive(self, message_id: str) -> bool:
        return False

    def label(self, message_id: str, label: str) -> bool:
        return False


def envelope_from_health(state: str, detail: str = "") -> dict:
    if state not in HEALTH_STATES:
        state = "error"
        detail = detail or "invalid health state reported"
    return {"state": state, "detail": detail}
