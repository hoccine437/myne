# comms/registry.py
"""Connector registry — capability discovery + health aggregation.

Only connectors that report configured() are ACTIVE; unconfigured/external
platforms simply never exist to the Core (no fake "connected" rows). One
failed connector degrades only itself — health() never raises, registry
swallows nothing silently (errors land in the health map + logs).
"""

from __future__ import annotations

from core import logging as log

# Built-in connectors are imported statically: constructing them touches no
# network and holds no credentials (env is read at call time), so this is
# free — and it keeps the module graph statically auditable.
from comms.connectors.email_connector import EmailConnector
from comms.connectors.telegram import TelegramConnector
from comms.connectors.phone_inbox import PhoneInboxConnector

_BUILTIN_CONNECTORS = (EmailConnector, TelegramConnector, PhoneInboxConnector)


class ConnectorRegistry:
    def __init__(self):
        self._connectors: dict[str, object] = {}
        self._built = False

    def _build(self):
        if self._built:
            return
        self._built = True
        for cls in _BUILTIN_CONNECTORS:
            try:
                connector = cls()
            except Exception as e:
                log.warning(f"comm connector {cls.__name__} failed to load: {e}")
                continue
            try:
                if connector.configured():
                    self._connectors[connector.platform] = connector
            except Exception as e:
                log.warning(f"comm connector {connector.name} config check failed: {e}")

    def invalidate(self) -> None:
        self._built = False
        self._connectors = {}

    def active(self) -> dict:
        self._build()
        return dict(self._connectors)

    def inject(self, connector) -> None:
        """Register a pre-built connector instance (test rigs, supervised
        custom connectors). Same contract as discovered connectors: it must
        implement the Connector interface; health probes will interrogate
        it like any other. `inject` never marks anything configured that
        isn't — it only swaps the implementation object."""
        self._build()
        self._connectors[connector.platform] = connector

    def eject(self, platform: str) -> None:
        self._connectors.pop(platform, None)

    def get(self, platform: str):
        """The connector serving a platform (phone_inbox serves 'phone' +
        'social'). Returns None when unconfigured — never a stub."""
        self._build()
        if platform in self._connectors:
            return self._connectors[platform]
        if platform in ("social",) and "phone" in self._connectors:
            return self._connectors["phone"]
        return None

    def health(self) -> dict:
        self._build()
        out = {}
        for platform, conn in self._connectors.items():
            try:
                out[platform] = conn.health()
            except Exception as e:
                out[platform] = {"state": "error", "detail": f"health probe raised: {e}"}
        return out

    def overall_state(self) -> str:
        states = [h.get("state") for h in self.health().values()]
        if not states:
            return "disconnected"
        if any(s == "error" for s in states):
            return "degraded"
        if any(s in ("connected", "authenticated", "available") for s in states):
            return "connected"
        return "disconnected"

    def poll_all_events(self) -> list:
        self._build()
        events = []
        for conn in self._connectors.values():
            try:
                events.extend(conn.poll_events())
            except Exception as e:
                log.warning(f"{conn.name} event poll failed: {e}")
        return events


connectors = ConnectorRegistry()
