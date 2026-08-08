# comms/connectors/email_connector.py
"""Email connector over the standard library — imaplib (read/search) and
smtplib (send). No third-party dependency; works on Termux.

AUTH: credentials come from environment variables ONLY (config.EMAIL_*).
They are read at connection time, never stored in the DB, audit log, or
filesystem. Absent credentials ⇒ configured() is False ⇒ the registry never
registered it ⇒ nothing downstream can pretend email exists.

Tests inject fake transports (imap_cls / smtp_cls / opener); live IMAP/SMTP
verification requires real authorized accounts (marked NOT VERIFIED in test
environments — never claimed otherwise).
"""

from __future__ import annotations

import socket
import time
from email.header import decode_header

import config
from comms.base import Connector, envelope_from_health
from comms.models import UnifiedMessage, Draft


def _decode(value) -> str:
    if not value:
        return ""
    parts = decode_header(str(value))
    out = []
    for text, enc in parts:
        try:
            out.append(text.decode(enc or "utf-8", "replace")
                       if isinstance(text, bytes) else str(text))
        except Exception:
            out.append(str(text))
    return " ".join(out)


class EmailConnector(Connector):
    name = "email"
    platform = "email"
    capabilities = frozenset({"read", "search", "send", "events"})

    def __init__(self, imap_cls=None, smtp_cls=None):
        self._imap_cls = imap_cls
        self._smtp_cls = smtp_cls
        self._last_error = ""

    # -- auth & health -----------------------------------------------------

    def configured(self) -> bool:
        return all([config.EMAIL_HOST, config.EMAIL_USER, config.EMAIL_PASSWORD])

    def health(self) -> dict:
        if not self.configured():
            return envelope_from_health("disconnected", "EMAIL_* not configured")
        if self._last_error:
            return envelope_from_health("error", self._last_error)
        try:
            sock = socket.create_connection(
                (config.EMAIL_HOST, config.EMAIL_IMAP_PORT), timeout=4)
            sock.close()
        except OSError as e:
            return envelope_from_health("error", f"imap host unreachable: {e}")
        return envelope_from_health("connected", "imap host reachable (auth on demand)")

    def _imap(self):
        cls = self._imap_cls
        if cls is None:
            import imaplib
            cls = imaplib.IMAP4_SSL
        conn = cls(config.EMAIL_HOST, config.EMAIL_IMAP_PORT)
        conn.login(config.EMAIL_USER, config.EMAIL_PASSWORD)
        return conn

    def _smtp(self):
        cls = self._smtp_cls
        if cls is None:
            import smtplib
            cls = smtplib.SMTP_SSL
        conn = cls(config.EMAIL_HOST, config.EMAIL_SMTP_PORT, timeout=20)
        conn.login(config.EMAIL_USER, config.EMAIL_PASSWORD)
        return conn

    # -- reads --------------------------------------------------------------

    def read(self, limit: int = 20) -> list:
        if not self.configured():
            return []
        msgs = []
        try:
            conn = self._imap()
            try:
                conn.select("INBOX")
                status, data = conn.search(None, "ALL")
                if status != "OK":
                    self._last_error = "search refused"
                    return []
                ids = data[0].split()[-int(limit):]
                for mid in reversed(ids):
                    status, payload = conn.fetch(mid, "(BODY.PEEK[HEADER.FIELDS "
                                                     "(FROM SUBJECT DATE MESSAGE-ID)])")
                    if status != "OK" or not payload or not payload[0]:
                        continue
                    raw = payload[0][1] if isinstance(payload[0], tuple) else payload[0]
                    text = raw.decode("utf-8", "replace")
                    sender = subject = message_id = ""
                    for line in text.splitlines():
                        low = line.lower()
                        if low.startswith("from:"):
                            sender = _decode(line.split(":", 1)[1].strip())
                        elif low.startswith("subject:"):
                            subject = _decode(line.split(":", 1)[1].strip())
                        elif low.startswith("message-id:"):
                            message_id = line.split(":", 1)[1].strip()
                    msgs.append(UnifiedMessage(
                        platform="email", account=config.EMAIL_USER,
                        sender=sender, content="", reply_context=subject,
                        conversation_id=message_id or subject,
                        permissions=("can_read", "can_send"),
                        message_id=f"email:{message_id}" if message_id else "",
                        timestamp=time.time()))
            finally:
                try:
                    conn.logout()
                except Exception:
                    pass
        except Exception as e:
            self._last_error = f"imap read failed: {e}"
            return []
        self._last_error = ""
        return msgs

    def search(self, query: str, limit: int = 20) -> list:
        # header-only search × local filter (imap full-text varies by server)
        return [m for m in self.read(limit=limit * 3)
                if query.lower() in (m.sender + " " + m.reply_context).lower()][:limit]

    def poll_events(self) -> list:
        return [m for m in self.read(limit=10)]

    # -- send ---------------------------------------------------------------

    def send(self, draft: Draft) -> dict:
        if getattr(draft, "platform", None) != "email":
            return {"ok": False, "platform_result": "platform mismatch"}
        if not self.configured():
            return {"ok": False, "platform_result": "email not configured"}
        if len(draft.body or "") > 40000:
            return {"ok": False, "platform_result": "body exceeds safety cap"}
        message = (
            f"From: {config.EMAIL_USER}\r\nTo: {draft.recipient}\r\n"
            f"Subject: {draft.subject or '(no subject)'}\r\n"
            f"Content-Type: text/plain; charset=utf-8\r\n\r\n{draft.body}"
        )
        try:
            conn = self._smtp()
            try:
                conn.sendmail(config.EMAIL_USER, [draft.recipient],
                              message.encode("utf-8"))
            finally:
                try:
                    conn.quit()
                except Exception:
                    pass
            return {"ok": True, "platform_result": "smtp accepted"}
        except Exception as e:
            return {"ok": False, "platform_result": f"smtp failed: {e}"}
