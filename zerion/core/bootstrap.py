# core/bootstrap.py
"""Zerion startup boundary — ONE authoritative preflight for every entry
point (main.py UI default, --terminal legacy loop, `python -m runtime`
service, `python -m ui.server` standalone).

Before this module existed, both entry points re-implemented:
  ConstitutionEngine.load() + config.validate() + tool warm-up.
Now they call bootstrap() and receive structured proof of what loaded
(constitution law count, tool registry size, config warnings) — the
ZERION SYSTEM CHECK lives in runtime/selfcheck.py; bootstrap is shorter
(what every path needs before it may serve an event) while selfcheck
is the full report.
"""

from __future__ import annotations

import time


def bootstrap(mode: str = "ui") -> dict:
    """Return a report; never raises (Constitution failure DOES raise —
    integrity aborts startup, by law EMR-001)."""
    started = time.monotonic()
    report = {"mode": mode, "started_at": time.time(), "completed_at": None}

    # constitutional integrity + config — the two startup invariants
    from constitution.constitution import ConstitutionEngine
    report["laws"] = len(ConstitutionEngine.load())

    import config
    report["config_warnings"] = config.validate()

    # canonical warmers: tool registry loads lazily on first use — one
    # cheap prime kills a first-turn hiccup on both front ends
    try:
        from tools.manager import tool_manager
        report["tools"] = len(tool_manager.list_tools())
    except Exception as e:
        report["tools"] = f"deferred: {e}"

    try:
        from agents import agent_pool
        report["agent_capacity"] = agent_pool.stats().get("capacity")
    except Exception as e:
        report["agent_capacity"] = f"deferred: {e}"

    report["completed_at"] = time.time()
    report["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
    return report
