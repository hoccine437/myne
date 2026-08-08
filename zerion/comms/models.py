# comms/models.py
"""Unified message + draft contracts for the Communication Layer.

Every platform normalizes into UnifiedMessage — the Cognitive Core never
sees provider-specific payloads. Fields per the canonical contract:
message_id, platform, account, sender, recipients, timestamp, content,
attachments, conversation_id, reply_context, permissions, status.

Nothing in this module holds credentials. `permissions` carries the
authorization facts a connector proved (scopes, account, can_send),
so downstream policy never has to trust a platform's word blindly.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field, asdict

PLATFORMS = ("email", "telegram", "phone", "social", "calendar", "local")

# inbox lifecycle
STATUS_RECEIVED = "received"
STATUS_CLASSIFIED = "classified"
STATUS_READ = "read"
STATUS_DRAFTED = "drafted"
STATUS_PENDING_APPROVAL = "pending_approval"
STATUS_APPROVED = "approved"
STATUS_SENT = "sent"
STATUS_FAILED = "failed"
STATUS_ARCHIVED = "archived"

# draft lifecycle
DRAFT_PREPARED = "prepared"
DRAFT_NEEDS_APPROVAL = "needs_approval"
DRAFT_APPROVED = "approved"
DRAFT_REJECTED = "rejected"
DRAFT_SENT = "sent"
DRAFT_FAILED = "failed"


@dataclass
class UnifiedMessage:
    platform: str
    sender: str
    content: str
    account: str = ""
    recipients: tuple = ()
    timestamp: float = field(default_factory=time.time)
    attachments: tuple = ()               # ({"name","mime","size","local_path"?}) — metadata only
    conversation_id: str = ""
    reply_context: str = ""               # quoted/original subject or thread title
    permissions: tuple = ()               # proven authorization facts ("can_read","can_send",...)
    status: str = STATUS_RECEIVED
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    classification: str = ""              # filled by comms.classify
    urgency: str = ""                     # low | normal | high | urgent

    def stable_id(self) -> str:
        """Platform-bound when the connector supplied a real message id
        ("tg:…" / email "<…>" style) — perfect redelivery dedupe. Otherwise
        a content+time-bucket heuristic (same text two minutes in a row IS
        two messages; a redelivered copy shares its timestamp)."""
        if self.message_id and (":" in self.message_id or "<" in self.message_id):
            key = f"{self.platform}|{self.message_id}"
        else:
            key = (f"{self.platform}|{self.account}|{self.sender}|"
                   f"{self.conversation_id}|{self.content[:120]}|{int(self.timestamp)}")
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["recipients"] = list(self.recipients)
        d["attachments"] = list(self.attachments)
        d["permissions"] = list(self.permissions)
        d["stable_id"] = self.stable_id()
        return d


@dataclass
class Draft:
    """A prepared-but-never-sent outbound item. Carries its own verification
    checklist results so approval screens show evidence, not vibes."""
    platform: str
    recipient: str
    body: str
    subject: str = ""
    conversation_id: str = ""
    account: str = ""
    tone: str = "casual"
    in_reply_to: str = ""
    attachments: tuple = ()
    generated_locally: bool = False       # True when no provider answered (offline template)
    checks: dict = field(default_factory=dict)  # recipient_ok/conversation_ok/content_ok/...
    risk_markers: tuple = ()
    status: str = DRAFT_PREPARED
    draft_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["attachments"] = list(self.attachments)
        d["risk_markers"] = list(self.risk_markers)
        return d
