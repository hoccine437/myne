# comms/connectors/telegram.py
"""Telegram connector via the official Bot API (HTTPS, stdlib urllib — no
extra packages, Termux-safe). Bot token from TELEGRAM_BOT_TOKEN only; the
token never enters the DB or audit log.

A bot can only see chats the account owner has interacted with; this mirrors
platform limitations honestly —  'read' means getUpdates history, not the
user's full Telegram account. Live delivery is NOT VERIFIED without a real
token (tests inject the HTTP transport).
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

import config
from comms.base import Connector, envelope_from_health
from comms.models import UnifiedMessage, Draft

_API = "https://api.telegram.org"


class TelegramConnector(Connector):
    name = "telegram"
    platform = "telegram"
    capabilities = frozenset({"read", "send", "events", "search"})

    def __init__(self, http=None, api_base: str = _API):
        self._http = http          # injected callable(url, data:dict)->dict
        self._api = api_base.rstrip("/")
        self._offset = 0
        self._me = None
        self._last_error = ""

    def _token(self) -> str:
        return config.TELEGRAM_BOT_TOKEN or ""

    def _call(self, method: str, **params) -> dict:
        if self._http is not None:
            return self._http(f"{self._api}/bot{self._token()}/{method}", params)
        url = f"{self._api}/bot{self._token()}/{method}?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310 — fixed host
            return json.loads(resp.read().decode("utf-8"))

    def configured(self) -> bool:
        return bool(self._token())

    def health(self) -> dict:
        if not self.configured():
            return envelope_from_health("disconnected", "TELEGRAM_BOT_TOKEN not set")
        if self._last_error:
            return envelope_from_health("error", self._last_error)
        try:
            data = self._call("getMe")
            if data.get("ok"):
                self._me = data.get("result") or {}
                return envelope_from_health(
                    "authenticated", f"bot @{self._me.get('username', '?')}")
            return envelope_from_health("error", "getMe refused")
        except Exception as e:
            return envelope_from_health("error", f"bot api unreachable: {e}")

    def _normalize(self, item: dict) -> UnifiedMessage | None:
        msg = item.get("message") or item.get("edited_message")
        if not msg:
            return None
        chat = msg.get("chat") or {}
        sender = (msg.get("from") or {}).get("username") or \
                 (msg.get("from") or {}).get("first_name", "")
        return UnifiedMessage(
            platform="telegram",
            account=str((self._me or {}).get("username", "")),
            sender=str(sender),
            content=str(msg.get("text", "") or msg.get("caption", "")),
            conversation_id=str(chat.get("id", "")),
            reply_context=str(chat.get("title", "") or sender),
            timestamp=float(msg.get("date", time.time())),
            permissions=("can_read", "can_send"),
            status="received",
            message_id=f"tg:{item.get('update_id')}:{msg.get('message_id')}")

    def poll_events(self) -> list:
        if not self.configured():
            return []
        try:
            data = self._call("getUpdates", offset=self._offset + 1,
                              timeout=0, limit=20)
        except Exception as e:
            self._last_error = f"poll failed: {e}"
            return []
        out = []
        for item in data.get("result") or []:
            self._offset = max(self._offset, int(item.get("update_id", 0)))
            msg = self._normalize(item)
            if msg is not None:
                out.append(msg)
        self._last_error = ""
        return out

    def read(self, limit: int = 20) -> list:
        return self.poll_events()[-int(limit):] if self.configured() else []

    def search(self, query: str, limit: int = 20) -> list:
        q = (query or "").lower()
        return [m for m in self.read(limit=limit * 5)
                if q in (m.content + " " + m.sender).lower()][:limit]

    def send(self, draft: Draft) -> dict:
        if draft.platform != "telegram":
            return {"ok": False, "platform_result": "platform mismatch"}
        if not self.configured():
            return {"ok": False, "platform_result": "bot token not configured"}
        if len(draft.body or "") > 4096:
            return {"ok": False, "platform_result": "telegram message cap is 4096 chars"}
        try:
            data = self._call("sendMessage", chat_id=draft.recipient,
                              text=draft.body[:4096])
            if data.get("ok"):
                return {"ok": True, "platform_result":
                        f"message_id {(data.get('result') or {}).get('message_id', '?')}"}
            return {"ok": False, "platform_result": str(data)[:200]}
        except Exception as e:
            return {"ok": False, "platform_result": f"send failed: {e}"}
