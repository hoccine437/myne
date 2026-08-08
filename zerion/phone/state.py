# phone/state.py
"""PhoneState — Zerion's live self-awareness of its physical body.

A single process-owned snapshot object the Core (and the UI bridge) can
observe at any time: battery, network, sensors, storage, IO availability,
capability registry, permission posture, in-flight action, last
verification result. Refreshed on a TTL cadence — the actual platform
call cost per refresh is small and bounded (probes are guarded).

Honesty rule: anything we cannot actually read is reported as None /
'unknown', never fabricated. The phone only answers what we can prove.
"""

from __future__ import annotations

import threading
import time

from phone.device import probe_device


class PhoneState:
    """Live device-state model owned by the PhoneBodyManager."""

    def __init__(self, discovery, adapter=None, ttl: float = 8.0):
        self._discovery = discovery
        self.adapter = adapter
        self.ttl = ttl
        self._lock = threading.Lock()
        self._cache: dict | None = None
        self._built_at = 0.0
        # live momentary fields written by the manager on action boundaries
        self.current_action = None            # action_id or None
        self.last_verified = None             # (capability, verified_state)
        self.denied_capabilities = set()      # capability → evidence message
        self.permissions = {"granted": [], "denied": [], "unknown": []}

    # ------------------------------------------------------------------

    def refresh(self, force: bool = False) -> dict:
        """TTL-cached snapshot; force=True only on action boundaries."""
        with self._lock:
            now = time.time()
            if self._cache is not None and not force and now - self._built_at < self.ttl:
                return self._cache
            self._built_at = now
            from phone.device import probe_device as _probe
            profile = _probe()
            caps = [(c.name, bool(c.available)) for c in self._discovery.capabilities()]
            available = sorted(n for n, ok in caps if ok)
            unavailable = sorted(n for n, ok in caps if not ok)
            self._cache = {
                "platform": profile.get("os"),
                "is_termux": profile.get("is_termux"),
                "is_mobile": profile.get("is_mobile"),
                "arch": profile.get("arch"),
                "battery": profile.get("battery"),
                "network": profile.get("network"),
                "storage": profile.get("storage"),
                "screen": profile.get("screen"),
                "memory": profile.get("memory"),
                "io": profile.get("io"),
                "available_capabilities": available,
                "unavailable_capabilities": sorted(set(unavailable) | set(self.denied_capabilities)),
                "capabilities_total": len(caps),
                "permissions": {
                    "granted": sorted(set(available) - set(self.denied_capabilities)),
                    "denied": sorted(self.denied_capabilities),
                    "unknown": sorted(set(unavailable) - set(available)),
                },
                "current_action": self.current_action,
                "last_verified": self.last_verified,
                "ts": now,
            }
            return self._cache

    def snapshot(self) -> dict:
        return self.refresh(force=False)

    # ------------------------------------------------------------------
    # manager hooks — tiny, explicit, state mutations only

    def note_action_started(self, action_id: str) -> None:
        with self._lock:
            self.current_action = action_id

    def note_action_finished(self, capability: str, verification: str) -> None:
        with self._lock:
            self.current_action = None
            self.last_verified = (capability, verification)

    def note_denied(self, capability: str, evidence: str) -> None:
        with self._lock:
            self.denied_capabilities.add(capability)
            self._cache = None  # next refresh rebuilds honest posture

    # ------------------------------------------------------------------
    # the self-aware questions (spec: "What can I do on this device?") —

    def what_can_i_do(self) -> list[tuple[str, str]]:
        snap = self.refresh()
        out = []
        granted = set(snap["permissions"]["granted"])
        for name in snap["available_capabilities"]:
            out.append((name, "ready"))
        return out

    def what_cant_i_do(self) -> list[str]:
        return list(self.refresh()["permissions"]["denied"] or
                    self.snapshot()["unavailable_capabilities"])

    def what_permissions(self) -> dict:
        return dict(self.refresh()["permissions"])

    def device_state(self) -> dict:
        s = self.refresh()
        return {k: s[k] for k in ("battery", "network", "storage", "screen",
                                   "memory", "io", "platform", "is_termux")}

    def current_action_desc(self) -> dict | None:
        return self.snapshot().get("current_action")

    def last_action_verification(self) -> tuple | None:
        return self.snapshot().get("last_verified")
