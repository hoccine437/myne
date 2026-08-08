# comms/reply.py
"""Intelligent reply engine.

Context assembly order (all existing systems, nothing duplicated):
  conversation history  (comms inbox, by conversation_id)
  contact context       (comms contacts — only what was explicitly stored)
  relevant memory       (knowledge.retrieve_context)
  user preferences      (long-term memory.json: tone/identity via minimal_memory)
  classification        (comms/classify: category + urgency drive tone)
  risk markers          (force confirmation later; also shape safety line)

Draft generation:
  online  → the existing provider chain via api.call_llm (Gemini), with a
            bounded drafting system prompt. The model DRAFTS; it never sends.
  offline → a local template, explicitly marked generated_locally=True.
            A template draft is honestly labeled — never impersonates
            model quality.

The engine returns a Draft object; storing/approving/sending is upstream.
"""

from __future__ import annotations

from comms import store
from comms.classify import classify_message, risk_markers, contains_task, extract_dates
from comms.models import Draft, UnifiedMessage
from core import logging as log

_TONE_RULES = {
    "urgent": "Be brief, direct, action-first; acknowledge urgency explicitly.",
    "financial": "Be precise and formal; restate amounts/refs verbatim; no promises.",
    "work": "Professional tone; structured sentences; include next step.",
    "personal": "Warm, first-name basis where known; short paragraphs.",
    "social": "Light and short; match the platform's conversational register.",
    "system": "Do not improvise; state the fact and the action taken.",
    "spam": "Do not draft a friendly reply.",
    "low": "Neutral, brief.",
    "technical": "Precise technical vocabulary; include evidence/steps.",
}

_DRAFT_SYSTEM = (
    "You draft short, truthful replies on behalf of the user's assistant. "
    "Rules: never fabricate facts, dates, names or commitments; never invent "
    "attachments; keep it under 120 words; match the requested tone; if "
    "information is missing, write the draft with a bracketed [ASK USER: x] "
    "placeholder instead of guessing; end without a fake signature."
)


def _tone_for(msg: UnifiedMessage) -> str:
    if msg.classification == "work":
        return "professional"
    if msg.classification == "urgent":
        return "urgent"
    if msg.classification in ("social", "personal"):
        return "casual"
    if msg.classification in ("financial", "system"):
        return "professional"
    return "technical" if msg.classification == "low" and msg.platform == "email" else "casual"


def _context_block(msg: UnifiedMessage, memory: dict) -> dict:
    block = {}
    history = store.conversation_history(msg.conversation_id, limit=6) \
        if msg.conversation_id else []
    if history:
        block["conversation"] = [
            {"sender": m["sender"], "content": m["content"][:240]} for m in history]
    contact = store.find_contact(msg.sender) if msg.sender else None
    if contact:
        block["contact"] = {"name": contact.get("name"),
                            "last_topic": contact.get("last_topic"),
                            "pending_tasks": contact.get("pending_tasks") or []}
    try:
        from knowledge.manager import KnowledgeManager
        recall = KnowledgeManager().retrieve_context(
            f"{msg.sender} {msg.content[:160]}", limit=4)
        if recall:
            block["relevant_memory"] = recall
    except Exception:
        pass
    if memory:
        keep = {k: v for k, v in memory.items()
                if k in ("user_name", "favorite_color", "favorite_food",
                         "favorite_music") and v}
        if keep:
            block["sender_preferences"] = keep
    return block


_ADDR_RE = __import__("re").compile(r"<([^<>\s]+@[^<>\s]+)>")


def _reply_target(msg: "UnifiedMessage") -> str:
    """Platform-correct send target: bare email for 'Name <addr>' senders,
    chat id for telegram (bots answer chats, not usernames), sender handle
    otherwise."""
    if msg.platform == "telegram":
        return msg.conversation_id or msg.sender
    if msg.platform == "email":
        m = _ADDR_RE.search(msg.sender or "")
        if m:
            return m.group(1)
    return msg.sender


def draft_reply(msg: UnifiedMessage, memory: dict | None = None,
                tone: str = "") -> Draft:
    """Build a Draft for an incoming message. Requires the caller to have
    already decided drafting is permitted (LEVEL >= 1)."""
    if not msg.classification:
        classify_message(msg)
    tone = tone or _tone_for(msg)
    context = _context_block(msg, memory or {})
    markers = risk_markers(msg.content)

    body = None
    generated_locally = False
    try:
        import api
        lines = [f"Platform: {msg.platform}", f"Incoming: {msg.content[:600]}"]
        if context.get("conversation"):
            lines.append("Recent conversation: " + " | ".join(
                f"{m['sender']}: {m['content']}" for m in context["conversation"][-3:]))
        if context.get("relevant_memory"):
            lines.append(f"Known context: {context['relevant_memory'][:400]}")
        lines.append(f"Tone: {tone} — {_TONE_RULES.get(tone, 'neutral and brief.')}")
        lines.append(f"Message classification: {msg.classification} ({msg.urgency})")
        body = api.call_llm(_DRAFT_SYSTEM, "\n".join(lines))
        body = (body or "").strip().strip('"')
    except Exception as e:
        log.debug(f"reply engine: provider unavailable, local template ({type(e).__name__})")
        body = None

    if not body:
        generated_locally = True
        task_hint = ""
        if contains_task(msg.content):
            task_hint = " I see a request in there — I'll confirm the details first."
        dates = extract_dates(msg.content)
        when = f" Re: {', '.join(dates[:2])} — I'll check the calendar." if dates else ""
        body = (f"Thanks for your message.{task_hint}{when} "
                f"I'll get back to you shortly. [draft-local]")

    draft = Draft(
        platform=msg.platform, recipient=_reply_target(msg), body=body,
        subject=f"Re: {msg.reply_context}" if msg.reply_context else "",
        conversation_id=msg.conversation_id, account=msg.account, tone=tone,
        in_reply_to=msg.message_id, generated_locally=generated_locally,
        risk_markers=markers,
    )
    return draft
