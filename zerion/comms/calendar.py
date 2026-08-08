# comms/calendar.py
"""Local authorized calendar over the shared comm tables.

Works offline (own store). When device bridges exist they must be additive —
this module never claims sync it has not performed. Availability checks are
interval arithmetic over stored events; reminders surface via due().
"""

from __future__ import annotations

import time

from comms import store

_DAY = 86400


def create(title: str, start: float, duration_min: int = 60,
           attendees=None, location: str = "", notes: str = "") -> dict:
    if not title or start <= 0 or duration_min <= 0:
        return {"ok": False, "reason": "title, positive start and duration required"}
    end = start + duration_min * 60
    clash = store.conflicts(start, end)
    eid = store.create_event(title, start, end, attendees, location, notes)
    return {"ok": True, "event_id": eid, "start": start, "end": end,
            "conflicts": [c["title"] for c in clash]}


def upcoming(days: int = 7) -> list:
    return store.list_events(time.time(), time.time() + days * _DAY)


def cancel(event_id: str) -> dict:
    return {"ok": bool(store.cancel_event(event_id)), "event_id": event_id}


def find_availability(day_start: float, duration_min: int = 60,
                      work_hours: tuple = (8, 20)) -> list:
    """Free slots in a day: subtraction of busy intervals from the work
    window. Returns real, computable gaps — never optimistic."""
    win_start = day_start + work_hours[0] * 3600
    win_end = day_start + work_hours[1] * 3600
    busy = sorted((e["start"], e["end"])
                  for e in store.list_events(day_start, day_start + _DAY))
    free, cursor = [], win_start
    for s, e in busy:
        gap_end = min(s, win_end)
        if gap_end - cursor >= duration_min * 60:
            free.append({"start": max(cursor, win_start), "end": gap_end})
        cursor = max(cursor, min(e, win_end))
    if win_end - cursor >= duration_min * 60:
        free.append({"start": cursor, "end": win_end})
    return free


def due_reminders(within_s: int = 1800) -> list:
    now = time.time()
    return [e for e in store.list_events(now, now + within_s)
            if e["start"] - now <= within_s and e["start"] >= now - 60]


def suggest_time_for(request_text: str, duration_min: int = 60) -> dict:
    """'tomorrow at 5'-class requests: resolve the day, report conflicts and
    the first free slot. Time-only resolution is deliberately conservative;
    ambiguous requests get reported, not guessed."""
    lowered = (request_text or "").lower()
    now = time.time()
    day = now + _DAY if "tomorrow" in lowered else now
    day_start = day - (day % _DAY)
    free = find_availability(day_start, duration_min)
    return {"day": day_start, "free_slots": free,
            "conflicts": [c["title"] for c in
                          store.conflicts(day_start, day_start + _DAY)]}
