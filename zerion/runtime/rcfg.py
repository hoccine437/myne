# runtime/rcfg.py
"""Runtime/service settings.

Separate from config.py on purpose: config.py is Core configuration,
read by the Core at import time. These are *service* settings (heartbeat
cadence, backoff limits, greeting text) used only by runtime/*. Same
defensive parsing style as config.py — a typo degrades to the documented
default and is surfaced, it never prevents startup.
"""

from __future__ import annotations

import os


def _int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


def _float(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# --- cadence (seconds) — deliberately conservative: a 24/7 service must
# idle at ~0% CPU, so nothing here is sub-second or busy -----------------
HEALTH_INTERVAL = _int("ZERION_HEALTH_INTERVAL", 15, minimum=2)
HEARTBEAT_INTERVAL = _int("ZERION_HEARTBEAT_INTERVAL", 5, minimum=1)
MAINTENANCE_INTERVAL = _int("ZERION_MAINTENANCE_INTERVAL", 900, minimum=60)
NETWORK_CHECK_INTERVAL = _int("ZERION_NETWORK_CHECK_INTERVAL", 300, minimum=60)

# --- recovery policy ------------------------------------------------------
RECOVERY_BACKOFF_BASE = _float("ZERION_BACKOFF_BASE", 2.0, minimum=0.5)
RECOVERY_BACKOFF_MAX = _float("ZERION_BACKOFF_MAX", 120.0, minimum=5.0)
MAX_RECOVERY_ATTEMPTS = _int("ZERION_MAX_RECOVERY_ATTEMPTS", 4, minimum=1)
RESTART_BUDGET = _int("ZERION_RESTART_BUDGET", 6, minimum=1)      # per window…
RESTART_WINDOW = _int("ZERION_RESTART_WINDOW", 3600, minimum=60)  # …seconds
FAILED_REPROBE_FACTOR = _int("ZERION_FAILED_REPROBE_FACTOR", 4, minimum=1)
# FAILED subsystems are re-probed at max_backoff * this factor, because
# external conditions (network, an audio player, an API token) can heal
# without any action from us.

# --- greeting -------------------------------------------------------------
GREETING_ENABLED = _bool("ZERION_GREETING_ENABLED", True)
GREETING_TEMPLATE = os.getenv(
    "ZERION_GREETING",
    "Welcome back{name}. Zerion is online and ready.",
)
GREETING_TIMEOUT = _float("ZERION_GREETING_TIMEOUT", 12.0, minimum=1.0)

# --- UI hosting -----------------------------------------------------------
UI_HOST = os.getenv("ZERION_UI_HOST", "0.0.0.0")
UI_PORT = _int("ZERION_UI_PORT", 8765, minimum=1)
