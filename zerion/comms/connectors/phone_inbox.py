# comms/connectors/phone_inbox.py
"""Phone notification + social-app intake through the EXISTING phone layer.

READ:  `termux-notification-list` (authorized OS mechanism) via the same
       TermuxAdapter the phone controllers already use. When the binary is
       absent, health is DISCONNECTED — never faked.
SOCIAL: social apps are reached through their *notifications* (WhatsApp,
        Messenger, …). We read the accessible notification text, classify,
        and can notify the user back. Deep in-app replies stay behind
        `open_url` deep links (existing SystemController) — this connector
        does NOT scrape apps or bypass Android security.
NOTIFY OUT: termux-notification (the existing NotificationController path).

This is the "supported social integration" surface: notification-content
reads + user-visible notices + supervised deep-link opens. It is PARTIAL by
platform design and documented as such in every honest state report.
"""

from __future__ import annotations

import json
import time

from comms.base import Connector, envelope_from_health
from comms.models import UnifiedMessage, Draft

_SOCIAL_PACKAGES = {
    "com.whatsapp": "whatsapp", "com.facebook.orca": "messenger",
    "org.telegram.messenger": "telegram-app", "com.instagram.android": "instagram",
    "com.twitter.android": "x", "com.zhiliaoapp.musically": "tiktok",
    "com.discord": "discord", "org.thoughtcrime.securesms": "signal",
}


class PhoneInboxConnector(Connector):
    name = "phone_inbox"
    platform = "phone"
    capabilities = frozenset({"read", "events"})

    def __init__(self, adapter=None):
        if adapter is None:
            from phone.adapter import TermuxAdapter
            adapter = TermuxAdapter()
        self.adapter = adapter
        self._last_error = ""

    def configured(self) -> bool:
        return True  # the connector can always exist; health reflects reality

    def health(self) -> dict:
        if not self.adapter.has("termux-notification-list"):
            return envelope_from_health(
                "disconnected", "termux-notification-list unavailable "
                                "(install/authorize Termux:API)")
        if self._last_error:
            return envelope_from_health("error", self._last_error)
        return envelope_from_health("connected", "notification listener available")

    def read(self, limit: int = 20) -> list:
        result = self.adapter.run("termux-notification-list", timeout=10)
        if not result.success:
            self._last_error = result.message[:160]
            return []
        self._last_error = ""
        try:
            items = json.loads(result.data or result.message or "[]")
            if not isinstance(items, list):
                return []
        except Exception:
            return []
        out = []
        for item in items[-int(limit):]:
            pkg = str(item.get("packageName", item.get("package", "")))
            app = _SOCIAL_PACKAGES.get(pkg, pkg.split(".")[-1] if pkg else "system")
            tag = str(item.get("tag") or item.get("id") or "")
            when = float(item.get("when", time.time() * 1000) or 0)
            if when > 1e12:
                when = when / 1000.0
            content = " — ".join(x for x in (item.get("title"), item.get("content"))
                                 if x)
            conv = f"{pkg}:{tag}" if tag else pkg
            out.append(UnifiedMessage(
                platform="social" if pkg in _SOCIAL_PACKAGES else "phone",
                account=app,
                sender=str(item.get("title", app)),
                content=str(content),
                conversation_id=conv,
                reply_context=app,
                permissions=("can_read",),
                message_id=f"pb:{conv}:{int(when or 0)}",
                timestamp=when or time.time()))
        return out

    def poll_events(self) -> list:
        return self.read(limit=10)

    # social "send" is intentionally unsupported here — replying inside an
    # app is done through supervised deep-link opens + draft handoff, never
    # background posting.
    def send(self, draft: Draft) -> dict:
        return {"ok": False,
                "platform_result": "in-app replies go through the supervised "
                                   "phone flow (deep link + prepared draft); "
                                   "direct send is not supported"}
