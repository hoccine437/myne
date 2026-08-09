# config.py
"""
Central configuration for Mark-X Lite.

All settings are read from environment variables (optionally loaded from a
.env file if python-dotenv is installed). Nothing here touches the network
or the filesystem beyond reading env vars, so importing this module is free.
"""

import os

# Configuration is imported very early by most modules. Environment values are
# therefore parsed defensively here: a typo must degrade to the documented
# default and appear in validate(), never prevent Zerion from starting.
_PARSE_WARNINGS: list[str] = []


def _env_int(name: str, default: int, minimum: int | None = None) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        _PARSE_WARNINGS.append(f"{name}={raw!r} is not an integer; using {default}.")
        return default
    if minimum is not None and value < minimum:
        _PARSE_WARNINGS.append(f"{name}={value} is below {minimum}; using {default}.")
        return default
    return value


def _env_float(name: str, default: float, minimum: float | None = None,
               maximum: float | None = None) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError:
        _PARSE_WARNINGS.append(f"{name}={raw!r} is not a number; using {default}.")
        return default
    if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        _PARSE_WARNINGS.append(f"{name}={value} is outside [{minimum}, {maximum}]; using {default}.")
        return default
    return value

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from dotenv import load_dotenv
    # Anchor the .env at the project root so Zerion works from ANY cwd —
    # the historical cwd-only load silently dropped keys when launched from
    # another directory (the classic "Zerion is offline" false mystery).
    load_dotenv(os.path.join(BASE_DIR, ".env"))
    load_dotenv()  # cwd .env still wins for ad-hoc overrides when different
except ImportError:
    # python-dotenv is optional; if it's missing we just rely on real
    # environment variables (export FOO=bar before running).
    pass

# ---------------------------------------------------------------------------
# Gemini-only provider selection
# ---------------------------------------------------------------------------
LLM_PROVIDER = "gemini"
_SUPPORTED_PROVIDERS = ("gemini",)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Configurable only: runtime code never embeds a model identifier.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-lite")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROMPT_PATH = os.path.join(BASE_DIR, "prompt.txt")
MEMORY_PATH = os.path.join(BASE_DIR, "memory", "memory.json")

# ---------------------------------------------------------------------------
# Voice output (optional, Gemini-powered)
# ---------------------------------------------------------------------------
# Speech is fully optional. If the API key, network, or an audio player is
# unavailable, the assistant keeps working via the keyboard/terminal only.
VOICE_ENABLED = os.getenv("VOICE_ENABLED", "true").strip().lower() in (
    "1", "true", "yes", "on"
)

# Kept for backward compatibility with older env files.
SPEECH_ENABLED = VOICE_ENABLED

VOICE_PROVIDER = os.getenv("VOICE_PROVIDER", "gemini").strip().lower()
GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")


def gemini_tts_supported() -> bool:
    """Conservative local guard: only explicitly named TTS models reach TTS.
    Checks for a "-tts" suffix (Gemini's actual naming convention, e.g.
    "gemini-2.5-flash-preview-tts") rather than a bare substring match --
    a substring check would also match names like "not-a-tts-model" that
    contain "tts" without actually being a TTS model."""
    model = GEMINI_TTS_MODEL.strip().lower()
    return model.endswith("-tts") or model.endswith("tts")

# One of Gemini's 30 prebuilt voice names (e.g. Kore, Puck, Charon, Zephyr).
# Charon is selected as the default calm, lower-register Gemini voice.
VOICE_NAME = os.getenv("VOICE_NAME", "Charon")

# "normal", "slow", or "fast" — expressed to Gemini TTS as a natural-language
# pacing instruction, since the API has no separate numeric speed parameter.
VOICE_SPEED = os.getenv("VOICE_SPEED", "normal").strip().lower()

# Gemini TTS auto-detects language from the text; this is kept for a future
# explicit-language use case and to satisfy the configuration surface.
VOICE_LANGUAGE = os.getenv("VOICE_LANGUAGE", "auto")

# 0.0-1.0. Playback volume isn't controllable per-clip through every backend
# player, so this is applied only where the player supports it (e.g. mpv).
VOICE_VOLUME = _env_float("VOICE_VOLUME", 1.0, minimum=0.0, maximum=1.0)

# Cache generated audio by a hash of the text, so repeated phrases don't
# re-hit the API. Cached files persist across runs; disable if disk-averse.
VOICE_CACHE = os.getenv("VOICE_CACHE", "true").strip().lower() in (
    "1", "true", "yes", "on"
)

# ---------------------------------------------------------------------------
# Communication Layer (comms/)
# ---------------------------------------------------------------------------
# Master switch for connectors + workflow scheduler. All offline machinery
# (inbox, classification, drafting fallback, workflows) works regardless;
# this gates only external platform traffic.
COMM_ENABLED = os.getenv("COMM_ENABLED", "true").strip().lower() in (
    "1", "true", "yes", "on"
)

# Approval levels: 0 observe, 1 draft, 2 confirm-before-send (default),
# 3 trusted automation (only for explicitly whitelisted low-risk rules).
COMM_DEFAULT_LEVEL = _env_int("COMM_DEFAULT_LEVEL", 2, minimum=0)

# Trusted-automation rules: JSON list of {"platform","account","recipient"}
# dicts. Empty by default — nothing is ever auto-sent out of the box.
COMM_TRUSTED_RAW = os.getenv("COMM_TRUSTED", "[]")

# Anti-abuse rails (hard caps; a draft counts against these once SENT).
COMM_RATE_PER_MINUTE = _env_int("COMM_RATE_PER_MINUTE", 12, minimum=1)
COMM_MAX_RECIPIENTS = _env_int("COMM_MAX_RECIPIENTS", 5, minimum=1)
COMM_DUPLICATE_WINDOW = _env_int("COMM_DUPLICATE_WINDOW", 3600, minimum=60)
COMM_RECIPIENT_COOLDOWN = _env_int("COMM_RECIPIENT_COOLDOWN", 20, minimum=0)

# Connector credentials: environment ONLY, never written to the knowledge
# DB, audit log, or any file. Absent credentials simply leave the connector
# unregistered — no failure, no fake "connected" state.
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_IMAP_PORT = _env_int("EMAIL_IMAP_PORT", 993, minimum=1)
EMAIL_SMTP_PORT = _env_int("EMAIL_SMTP_PORT", 465, minimum=1)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Background autonomous communication (comms/autopilot.py): the pump and
# event pipeline run when enabled; autonomous SENDS still require the
# trusted-rule ladder (no sending without explicit authorization anywhere).
AUTOPILOT_ENABLED = os.getenv("AUTOPILOT_ENABLED", "true").strip().lower() in (
    "1", "true", "yes", "on"
)
# New platforms start in shadow mode (observe + draft, nothing sent) until
# the owner graduates them with evidence.
COMM_SHADOW_DEFAULT = os.getenv("COMM_SHADOW_DEFAULT", "true").strip().lower() in (
    "1", "true", "yes", "on"
)
# Background replies require an explicit authorized workflow object
# (comms/bgworkflows.py). "Reply to people on X" starts one with a TTL;
# without one, the autopilot only observes. Never false in production.
COMM_REQUIRE_FLOW = os.getenv("COMM_REQUIRE_FLOW", "true").strip().lower() in (
    "1", "true", "yes", "on"
)
COMM_FLOW_TTL = _env_int("COMM_FLOW_TTL", 86400, minimum=300)
# Serious Mode attempt throttling (authentication guard)
SERIOUS_MAX_ATTEMPTS = _env_int("SERIOUS_MAX_ATTEMPTS", 3, minimum=1)
SERIOUS_LOCKOUT_S = _env_int("SERIOUS_LOCKOUT_S", 300, minimum=10)

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT = _env_int("REQUEST_TIMEOUT", 30, minimum=1)
MAX_HISTORY = _env_int("MAX_HISTORY", 5, minimum=0)

# ---------------------------------------------------------------------------
# Planning engine
# ---------------------------------------------------------------------------
# Two-layer gate. PLANNER_ENABLED (bool) is the live toggle (UI settings and
# tests write it). PLANNER_MODE is the routing policy from env:
#   "on"   — every classification-driven planning signal goes to the LLM
#            decomposer (legacy eager behavior),
#   "off"  — never plan,
#   "auto" — DEFAULT: plan only when the classifier actually detects a
#            multi-step request (needs_planning), i.e. complexity escalation
#            is automatic but trivial turns stay free. (mission §9)
PLANNER_ENABLED = os.getenv("PLANNER_ENABLED", "false").strip().lower() in (
    "1", "true", "yes", "on"
)
_PLANNER_MODE_ENV = os.getenv("PLANNER_MODE", "").strip().lower()
PLANNER_MODE = _PLANNER_MODE_ENV or ("on" if PLANNER_ENABLED else "auto")


def planner_active(needs_planning: bool) -> bool:
    """The one routing rule for the whole turn pipeline (main.py and
    ui/session.py call this; never read PLANNER_* directly).

    Semantics:
      PLANNER_MODE=off  → never plan
      PLANNER_MODE=on   → always plan on planner-shaped classification
      PLANNER_MODE=auto (default) → plan only when the classifier saw a
                         multi-step request. Complexity routing is automatic;
                         TRIVIAL turns never pay the extra LLM call (the
                         classifier computes needs_planning for free). The
                         legacy PLANNER_ENABLED toggle keeps its historical
                         meaning (eager) only in the 'on' mode contract.
    """
    if PLANNER_MODE == "off":
        return False
    if PLANNER_MODE == "on":
        return True
    return bool(needs_planning)

# Skip the decomposition call entirely for very short messages (greetings,
# one-word replies) — these are essentially never multi-step requests, so
# this avoids paying the extra LLM call on the most common kind of turn.
PLANNER_MIN_WORDS = _env_int("PLANNER_MIN_WORDS", 4, minimum=0)

# ---------------------------------------------------------------------------
# Agent Orchestration
# ---------------------------------------------------------------------------
# When the Intent Engine can't answer locally and the request classifies as
# ordinary chat covering 2+ specialist domains, the canonical Orchestrator
# (agents/orchestrator.py) is consulted BEFORE paying for an LLM call: its
# lanes are bounded, whitelisted, read-only, and the whole consult is
# evidence-gated (no useful lanes → the turn falls through to the LLM
# exactly as before). Disable to restore the pre-integration behavior.
ORCHESTRATION_ENABLED = os.getenv("ORCHESTRATION_ENABLED", "true").strip().lower() in (
    "1", "true", "yes", "on"
)

# ---------------------------------------------------------------------------
# Self-Critic
# ---------------------------------------------------------------------------
# The Self-Critic reviews a draft chat response before it's sent, using
# cheap structural checks plus this turn's reasoning confidence, and
# rewrites it once if a real issue is found. Fully optional: when
# disabled, main.py's pipeline is unchanged from before the critic existed.
ENABLE_SELF_CRITIC = os.getenv("ENABLE_SELF_CRITIC", "true").strip().lower() in (
    "1", "true", "yes", "on"
)

# Below this confidence, review() flags the response for improvement even
# if no structural issue was found. Matches the range
# cognition.reasoning.CognitiveReasoningEngine.reason() actually produces
# (.35 floor, .9 ceiling).
LOW_CONFIDENCE_THRESHOLD = _env_float("LOW_CONFIDENCE_THRESHOLD", 0.45, minimum=0.0, maximum=1.0)

# A response shorter than this (after stripping) is flagged as too short
# to be a useful answer.
MINIMUM_RESPONSE_LENGTH = _env_int("MINIMUM_RESPONSE_LENGTH", 3, minimum=0)

# Hard ceiling on improve passes per turn. The critic never re-reviews its
# own output, so this is a defensive cap, not a normal retry loop -- at
# most this many api.call_llm() calls happen for the critic in one turn.
MAXIMUM_IMPROVEMENT_ATTEMPTS = _env_int("MAXIMUM_IMPROVEMENT_ATTEMPTS", 1, minimum=0)

# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------

def validate() -> list:
    """Return a list of human-readable warnings about missing/incomplete
    configuration. Never raises — callers decide how loudly to report."""
    warnings = list(_PARSE_WARNINGS)
    warnings.extend([
        f"Text model: {GEMINI_MODEL}",
        f"Speech model: {GEMINI_TTS_MODEL}",
        f"TTS supported: {'YES' if gemini_tts_supported() else 'NO'}",
        f"Self-Critic: {'enabled' if ENABLE_SELF_CRITIC else 'disabled'}",
        f"Orchestration: {'enabled' if ORCHESTRATION_ENABLED else 'disabled'}",
    ])

    if LLM_PROVIDER not in _SUPPORTED_PROVIDERS:
        warnings.append(
            f"Unknown LLM_PROVIDER '{LLM_PROVIDER}' (supported: {', '.join(_SUPPORTED_PROVIDERS)}); "
            f"falling back to gemini."
        )

    if not GEMINI_API_KEY:
        warnings.append("GEMINI_API_KEY is not set.")
    if not GEMINI_MODEL.strip():
        warnings.append("GEMINI_MODEL is empty.")

    if not os.path.exists(PROMPT_PATH):
        warnings.append(f"prompt.txt not found at {PROMPT_PATH}.")
    if VOICE_PROVIDER != "gemini":
        warnings.append(f"VOICE_PROVIDER must be gemini; got {VOICE_PROVIDER!r}.")
    if VOICE_ENABLED and VOICE_PROVIDER == "gemini" and not GEMINI_API_KEY:
        warnings.append("VOICE_ENABLED is true but GEMINI_API_KEY is not set — speech is disabled.")
    if VOICE_ENABLED and VOICE_PROVIDER == "gemini" and not gemini_tts_supported():
        warnings.append(f"GEMINI_TTS_MODEL '{GEMINI_TTS_MODEL}' is not explicitly a TTS model — speech is disabled.")
    if REQUEST_TIMEOUT <= 0:
        warnings.append(f"REQUEST_TIMEOUT is {REQUEST_TIMEOUT} (must be positive); using it as-is may hang.")
    if MAX_HISTORY < 0:
        warnings.append(f"MAX_HISTORY is {MAX_HISTORY} (must be >= 0).")

    return warnings
