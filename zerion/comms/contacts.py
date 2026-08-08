# comms/contacts.py
"""Contact intelligence — lookup, identification, minimal context.

Sources, in trust order:
  1. the local contact book (comm_contacts) — entries arrive only from
     explicit user input, device sync, or observed inbox correspondents
  2. the device address book via `termux-contact-list` (authorized OS
     mechanism, binary- and permission-gated; one-shot import on demand)

Deliberately minimal: name, identifiers (number/handle/email), platforms,
last_topic, pending_tasks. No attribute inference, no profiling.
"""

from __future__ import annotations

import json

from comms import store
from core import logging as log


def lookup(query: str) -> dict | None:
    book = store.find_contact(query)
    if book is not None:
        return book
    # fall through to the device book only when asked for something we do
    # not already know (keeps device reads rare and purposeful)
    return device_lookup(query)


def device_lookup(query: str) -> dict | None:
    try:
        from phone.adapter import TermuxAdapter
        adapter = TermuxAdapter()
        if not adapter.has("termux-contact-list"):
            return None
        result = adapter.run("termux-contact-list", timeout=10)
        if not result.success:
            return None
        data = json.loads(result.data or result.message or "[]")
    except Exception as e:
        log.debug(f"device contact lookup unavailable: {e}")
        return None
    q = (query or "").strip().lower()
    if not q:
        return None
    for entry in data:
        name = str(entry.get("name", ""))
        number = str(entry.get("number", entry.get("phone", "")))
        if q in name.lower() or q == number:
            store.upsert_contact(name or number, identifier=number)
            return store.find_contact(name or number)
    return None


def sync_from_inbox(limit: int = 100) -> int:
    """Learn correspondents FROM OUR OWN INBOX (not from any profile
    building): one contact row per observed sender, no content kept."""
    n = 0
    for row in store.query_messages(limit=limit):
        sender = row.get("sender")
        if not sender:
            continue
        try:
            store.upsert_contact(sender, platform=row.get("platform", ""))
            n += 1
        except Exception:
            continue
    return n


def context_for(sender: str) -> dict:
    contact = store.find_contact(sender)
    if not contact:
        return {}
    return {"name": contact.get("name"), "platforms": contact.get("platforms"),
            "last_topic": contact.get("last_topic"),
            "pending_tasks": contact.get("pending_tasks") or []}
