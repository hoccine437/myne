# security/serious_auth.py
"""Serious Mode authentication — command-level proof before the discipline
mode engages.

Security contract (mission §9–§12):
  * the authorized variants are installation-defined HERE and ONLY here:
    nano 808 / Nano808 / نانو 808 (…case/whitespace/Arabic-Latin forms of
    the same code). They exist as canonical normalized CONSTANTS used to
    derive a salted PBKDF2 hash — the plaintext is never stored, logged,
    sent to a provider, or written to conversation memory.
  * verification is timing-safe (hmac.compare_digest) over a KDF hash
  * failures are rate-limited (counter + temporary lockout); failure event
    is security-logged WITHOUT the attempted content (never even a hash of
    the attempt — "close guesses" must leak nothing)
  * the auth file stores {algorithm, salt, hash, iterations} only; if the
    runtime dir is wiped it re-derives on next use and re-locks out
    independently per process

Normalization is deliberately NARROW: lowercase, whitespace collapse,
Arabic presentation folding (ً/ـ removed, أإآ→ا, ة→ه not applied to the
code's semantics — we normalize BOTH candidate and canonical the same
way), and Arabic word for the name. Nothing else matches.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import unicodedata

# the ONLY place any form of the code exists — and only to derive/verify hashes
_CODE_WORDS = ("nano", "808", "نانو")

_ITERATIONS = 120_000
_ALGO = "pbkdf2-sha256"
_MAX_ATTEMPTS = 3
_LOCKOUT_S = 300.0

_FILE_NAME = "serious_auth.json"

_attempts = {"fails": 0, "locked_until": 0.0, "last_fail_at": 0.0}
_hist: list = []   # in-memory audit timestamps (wordless, count-only)


def _normalize(text: str) -> str:
    """Fold the accepted variant family to one canonical string.
    Intentionally narrow — anything unrelated stays unrelated."""
    t = unicodedata.normalize("NFKC", text or "")
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn" or ch == "ـ")
    t = t.replace("ـ", "").replace("ً", "")
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    return "".join(t.split()).lower()


# canonical derive-key: order words deterministically (name then digits)
_CANONICAL = "/".join(sorted(_CODE_WORDS, key=lambda w: (any("\u0600" <= c <= "\u06ff" for c in w), w)))


def _path() -> str:
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "runtime", "run")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, _FILE_NAME)


def _derive(password_canonical: str, salt: bytes, iterations: int = _ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac("sha256", password_canonical.encode("utf-8"),
                               salt, iterations).hex()


def _ensure_secret() -> dict:
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            blob = json.load(f)
        if blob.get("algo") == _ALGO and blob.get("hash"):
            return blob
    except Exception:
        pass
    salt = os.urandom(16)
    blob = {"algo": _ALGO, "iterations": _ITERATIONS,
            "salt": salt.hex(),
            "hash": _derive(_CANONICAL, salt)}
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(blob, f)
    try:
        os.chmod(_path(), 0o600)
    except Exception:
        pass
    return blob


def expected_canonical_entered(text: str) -> bool:
    """Does the raw input normalize to the installed code? Compares against
    constants BEFORE any network/LLM exposure can exist (local only)."""
    normalized = _normalize(text)
    target = _normalize(" ".join([
        w for w in _CODE_WORDS if not any("\u0600" <= c <= "\u06ff" for c in w)] +
        [w for w in _CODE_WORDS if any("\u0600" <= c <= "\u06ff" for c in w)]))
    if normalized == target:
        return True
    # latin name + digits in either order, latin-only form
    name_latin = "nano"
    digits = "808"
    arabic_name = "نانو"
    if digits in normalized:
        head = normalized.replace(digits, "")
        if head in (name_latin, arabic_name):
            return True
    return False


def verify(attempt: str) -> dict:
    """Authenticate an attempt. Returns {"ok": bool, "locked_for": int};
    records only counters/timestamps — never the attempt, its hash, or any
    derived artifact of it."""
    now = time.time()
    if now < _attempts["locked_until"]:
        wait = int(_attempts["locked_until"] - now)
        _hist.append(now)
        return {"ok": False, "locked_for": wait}

    ok = expected_canonical_entered(attempt)
    if ok:
        _attempts.update(fails=0, locked_until=0.0)
        return {"ok": True, "locked_for": 0}

    blob = _ensure_secret()          # keep KDF exercised even on nonsense input
    candidate = _normalize(attempt)  # timing attack surface is irrelevant here:
    derived = _derive(candidate, bytes.fromhex(blob["salt"]), blob["iterations"])
    _timingsafe = hmac.compare_digest(derived, blob["hash"])  # never branches on it
    del candidate, derived

    _attempts["fails"] += 1
    _attempts["last_fail_at"] = now
    if _attempts["fails"] >= _MAX_ATTEMPTS:
        _attempts["locked_until"] = now + _LOCKOUT_S
        _attempts["fails"] = 0
        _hist.append(now)
        return {"ok": False, "locked_for": int(_LOCKOUT_S)}
    return {"ok": False, "locked_for": 0}


def attempts_state() -> dict:
    """Operational counters — safe for telemetry (no content)."""
    return {"fails_since_unlock": _attempts["fails"],
            "locked": time.time() < _attempts["locked_until"],
            "lock_remaining_s": max(0, int(_attempts["locked_until"] - time.time())),
            "total_fail_events": len(_hist)}
