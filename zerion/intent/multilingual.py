# intent/multilingual.py
"""Multilingual, semantic (not exact-string) command recognition.

Design: normalize aggressively (case, whitespace, Arabic letter-fold,
tatweel/diacritics, common Darija spellings) then SCORE intents by
composable token evidence (topic set + action set + negation handling).
Adding a language means adding stems, never forking logic.

Recognized intents:
  ENABLE_SERIOUS_MODE / DISABLE_SERIOUS_MODE
  START_COMM_FLOW(platform) / STOP_COMM_FLOW(platform-or-none)
  COMM_PAUSE / ESTOP_ALL

Examples that must land identically:
  "Turn on serious mode", "شغل الوضع الجاد", "فعل Serious Mode"
  "Reply to people on Instagram", "رد على الناس في انستغرام", "جاوب الناس فالانستا"
"""

from __future__ import annotations

import unicodedata

# ---- normalization ------------------------------------------------------

def fold(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    # strip arabic diacritics + tatweel, fold letterforms
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    t = t.replace("ـ", "")
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"),
                 ("ؤ", "و"), ("ئ", "ي"), ("'", " "), ("’", " ")):
        t = t.replace(a, b)
    return " ".join(t.lower().split())


# ---- token stems (any one of a set counts as evidence) ------------------

_SERIOUS = ("serious", "serieuse", "sérieux", "serio", "جاد", "الجاد", "جدي")
_MODE = ("mode", "mod", "وضع", "الوضع", "وضعية", "نمط")
_ON = ("on", "enable", "activate", "turn on", "switch on", "start",
       "شغل", "شغال", "فعل", "فعال", "فعّل", "خلي", "ادخل", "دخل", "حط")
_OFF = ("off", "disable", "deactivate", "turn off", "exit", "stop", "خروج",
        "حبس", "سكر", "عطل", "عطّل", "اطفي", "اخرج", "أخرج", "وقف", "اقف")

_REPLY_VERBS = ("reply", "respond", "answer", "رد", "ردّ", "جاوب",
                "جواب", "جاوبي", "ارود", "الرد", "در", "ردود")
_PEOPLE_MSG = ("people", "messages", "msgs", "dm", "dms", "الناس", "رسائل",
               "الرسائل", "ميساجات", "الميساجات", "الميساج", "ميساج",
               "ديراكت", "الديراكت", "الخاص")
_PLATFORM_ALIASES = {
    "instagram": ("instagram", "insta", "انستا", "انستغرام", "إنستغرام",
                  "انستجرام", "الانستا", "الانستغرام", "الإنستغرام", "انستقرام"),
    "telegram": ("telegram", "تيليغرام", "تليجرام", "التيليجرام"),
    "whatsapp": ("whatsapp", "واتساب", "واتس", "الواتساب"),
    "email": ("email", "e-mail", "mail", "gmail", "بريد", "الايميل",
              "الإيميل", "ايميل", "المايل"),
    "social": ("social", "رسائل السوشال", "السوشال"),
    "phone": ("phone", "الهاتف", "الرسائل النصية", "sms", "sms"),
}
_STOP_FLOW = ("stop", "pause", "disable", "حبس", "وقف", "وقفي", "اقف",
              "سكر", "سكري", "عطل", "عطّل", "ارحم", "كفي")
_ALL_COMM = ("all communication", "everything", "كل شي", "كلشي", "كولشي",
             "كل الاتصالات", "جميع")

_ACTIVATION = ("start", "begin", "launch", "enable", "بدا", "ابدا", "بدي")


def _any(text: str, variants) -> bool:
    return any(v in text for v in variants)


def match(text: str) -> dict | None:
    """Return {"intent": name, "platform": optional, "confidence": float}
    or None. Conservative on purpose: absent topic or absent action = None
    (falls through to the ordinary pipeline instead of guessing)."""
    t = fold(text)
    if not t or len(t) < 3:
        return None

    has_serious = _any(t, _SERIOUS)
    has_mode = _any(t, _MODE)
    if has_serious and (has_mode or _any(t, _ON) or _any(t, _OFF)):
        if _any(t, _OFF):
            return {"intent": "DISABLE_SERIOUS_MODE", "confidence": .9}
        return {"intent": "ENABLE_SERIOUS_MODE", "confidence": .9}

    # communication-flow commands need a platform-or-all signal AND a verb
    platform = next((p for p, aliases in _PLATFORM_ALIASES.items()
                     if _any(t, aliases)), None)
    # negation guard: "don't reply" never starts a flow (folded forms —
    # apostrophes fold to spaces: "don't" → "don t")
    negated = (_any(t, ("don't", "dont", "don t", "do not", "never",
                        " لا ", "بلا", "بدون", "ماشي", "مش "))
               or t.startswith("ما ") or t.startswith("لا "))
    if platform and _any(t, _STOP_FLOW) and not negated:
        return {"intent": "STOP_COMM_FLOW", "platform": platform, "confidence": .85}
    if platform and (_any(t, _REPLY_VERBS) or _any(t, _ACTIVATION)) and not negated:
        if _any(t, _PEOPLE_MSG) or _any(t, _REPLY_VERBS):
            return {"intent": "START_COMM_FLOW", "platform": platform,
                    "confidence": .85}

    if (_any(t, _STOP_FLOW) and _any(t, ("communication", "الاتصالات",
                                         "التواصل", "الردود", "الرسائل"))) or \
       (_any(t, ("stop all", "stop everything")) and not negated):
        return {"intent": "ESTOP_ALL", "confidence": .9}
    if _any(t, ("resume", "restart", "start again")) and \
       _any(t, ("communication", "الاتصالات", "التواصل")):
        return {"intent": "RESUME_COMM", "confidence": .85}
    if _any(t, ("رجع الاتصالات", "شغل الاتصالات", "فتح الاتصالات")):
        return {"intent": "RESUME_COMM", "confidence": .85}
    return None
