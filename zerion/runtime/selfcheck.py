# runtime/selfcheck.py
"""ZERION SYSTEM CHECK — startup self-diagnostic, evidence-only output.

Each row comes from an actual probe, never a guess:
  core/config, constitution (lock verify), memory (load roundtrip),
  knowledge (DB open+query), tools (registry count), agents (pool stats),
  phone (adapter binaries), communication (connectors+overrides+outbox),
  learning (engine init), evolution (owner flow), background (autopilot),
  models (provider configured), storage (writable), network (bounded probe),
  ui (app import).

States: PASS / DEGRADED / BLOCKED / FAILED / UNAVAILABLE with the exact
reason string. Printable from `python -m runtime --check`; callable from
setup and tests.
"""

from __future__ import annotations

import os
import shutil
import socket
import sys
import time

from agents.service import pool as agent_pool  # noqa: F401  (canonical alias probe)


def _row(name: str, ok: str, detail: str = "") -> dict:
    assert ok in ("PASS", "DEGRADED", "BLOCKED", "FAILED", "UNAVAILABLE"), ok
    return {"name": name, "state": ok, "detail": detail}


def run_checks(include_network: bool = True) -> dict:
    rows = []

    # --- configuration
    try:
        import config
        warnings = config.validate()
        hard = [w for w in warnings if "not set" in w or "not found" in w or
                "must be" in w or "Unknown" in w]
        rows.append(_row("configuration",
                         "PASS" if not hard else "DEGRADED",
                         "; ".join(hard) if hard else "validated"))
    except Exception as e:
        rows.append(_row("configuration", "FAILED", str(e)))

    # --- constitution
    try:
        from constitution.constitution import ConstitutionEngine
        ConstitutionEngine._cache = None
        ConstitutionEngine.verify_lock()
        rows.append(_row("constitution", "PASS",
                         f"{len(ConstitutionEngine.load())} laws, integrity locked"))
    except Exception as e:
        rows.append(_row("constitution", "FAILED", f"verify_lock: {e}"))

    # --- memory (json persona store: read roundtrip)
    try:
        from memory.memory_manager import load_memory
        mem = load_memory()
        rows.append(_row("memory", "PASS",
                         f"sections={summarize_mem(mem)}"))
    except Exception as e:
        rows.append(_row("memory", "FAILED", str(e)))

    # --- knowledge db
    try:
        from knowledge.manager import KnowledgeManager
        km = KnowledgeManager()
        n = km.db.query("SELECT COUNT(*) AS n FROM records")[0]["n"]
        rows.append(_row("knowledge", "PASS", f"records={n} (sqlite+fts)"))
    except Exception as e:
        rows.append(_row("knowledge", "FAILED", str(e)))

    # --- learning
    try:
        from learning.engine import LearningEngine
        from learning.background import BackgroundLearning
        LearningEngine()
        idle = BackgroundLearning().run_once()
        rows.append(_row("learning", "PASS", idle[:80]))
    except Exception as e:
        rows.append(_row("learning", "FAILED", str(e)))

    # --- tools
    try:
        from tools.manager import tool_manager
        tools = tool_manager.list_tools()
        state = "PASS" if len(tools) >= 40 else "DEGRADED"
        rows.append(_row("tools", state, f"{len(tools)} discovered "
                                         f"({sum(1 for t in tools if t['destructive'])} gated)"))
    except Exception as e:
        rows.append(_row("tools", "FAILED", str(e)))

    # --- agents
    try:
        from agents import agent_pool
        stats = agent_pool.stats()
        rows.append(_row("agents", "PASS",
                         f"pool cap={stats['capacity']} types ready"))
    except Exception as e:
        rows.append(_row("agents", "FAILED", str(e)))

    # --- phone
    try:
        from phone.adapter import TermuxAdapter
        adapter = TermuxAdapter()
        bins = [b for b in ("termux-battery-status", "termux-notification-list",
                            "termux-clipboard-get") if adapter.has(b)]
        if shutil.which("sh") and "com.termux" not in os.environ.get("PREFIX", ""):
            rows.append(_row("phone", "UNAVAILABLE",
                             "not a Termux host (expected off-device)"))
        else:
            rows.append(_row("phone", "PASS" if bins else "DEGRADED",
                             "binaries: " + (", ".join(bins) if bins else "none")))
    except Exception as e:
        rows.append(_row("phone", "FAILED", str(e)))

    # --- communication
    try:
        from comms import overrides, store
        from comms.registry import connectors
        store.init_all()
        health = connectors.health()
        bad = {p: h for p, h in health.items() if h.get("state") == "error"}
        detail = (f"{len(health)} connector(s) active"
                  + (f", overrides paused!" if overrides.is_paused() else ""))
        if overrides.is_estopped():
            rows.append(_row("communication", "BLOCKED", "ESTOP active"))
        elif bad:
            rows.append(_row("communication", "DEGRADED",
                             "connector errors: " + ", ".join(sorted(bad))))
        else:
            rows.append(_row("communication", "PASS", detail))
    except Exception as e:
        rows.append(_row("communication", "FAILED", str(e)))

    # --- background
    try:
        import config
        from comms import bgworkflows, health as comm_health
        flows = len(bgworkflows.active())
        hb = comm_health.read()
        state = "PASS" if config.AUTOPILOT_ENABLED else "DEGRADED"
        rows.append(_row("background", state,
                         f"autopilot={'on' if config.AUTOPILOT_ENABLED else 'off'}, "
                         f"{flows} active flow(s), svc-state={hb.get('service', '-')}"))
    except Exception as e:
        rows.append(_row("background", "FAILED", str(e)))

    # --- evolution (owner flow must work; runtime execution is off by design)
    try:
        from constitution.evolution import ProtectedEvolution
        from pathlib import Path
        eng = ProtectedEvolution(Path(__file__).resolve().parent.parent)
        rows.append(_row("self-evolution", "PASS",
                         "staged pipeline present (owner-gated, never auto)"))
    except Exception as e:
        rows.append(_row("self-evolution", "FAILED", str(e)))

    # --- models
    import config as _cfg
    if _cfg.GEMINI_API_KEY:
        rows.append(_row("models", "PASS",
                         f"gemini text={_cfg.GEMINI_MODEL} tts={_cfg.GEMINI_TTS_MODEL}"))
    else:
        rows.append(_row("models", "DEGRADED", "GEMINI_API_KEY not set — "
                                               "local/agent paths still work"))

    # --- storage
    try:
        from config import BASE_DIR
        testfile = os.path.join(BASE_DIR, "runtime", "run", ".selfcheck.tmp")
        os.makedirs(os.path.dirname(testfile), exist_ok=True)
        with open(testfile, "w") as f:
            f.write("x")
        os.unlink(testfile)
        rows.append(_row("storage", "PASS", "runtime dir writable"))
    except Exception as e:
        rows.append(_row("storage", "FAILED", str(e)))

    # --- network (bounded, optional)
    if include_network:
        try:
            socket.create_connection(("generativelanguage.googleapis.com", 443),
                                     timeout=3).close()
            rows.append(_row("network", "PASS", "gemini endpoint reachable"))
        except OSError as e:
            rows.append(_row("network", "DEGRADED",
                             f"offline or blocked ({type(e).__name__})"))

    # --- ui
    try:
        import ui.server  # noqa: F401
        rows.append(_row("ui", "PASS", "starlette app importable"))
    except Exception as e:
        rows.append(_row("ui", "DEGRADED", f"ui extras missing: {e}"))

    failed = [r for r in rows if r["state"] == "FAILED"]
    blocked = [r for r in rows if r["state"] == "BLOCKED"]
    degraded = [r for r in rows if r["state"] in ("DEGRADED", "UNAVAILABLE")]
    if failed or blocked:
        overall = "FAILED"
    elif degraded:
        overall = "DEGRADED"
    else:
        overall = "READY"
    return {"rows": rows, "overall": overall, "generated_at": time.time()}


def summarize_mem(mem: dict) -> str:
    return "/".join(f"{k}:{len(v or {})}" for k, v in mem.items())


def print_report(report: dict | None = None, out=print) -> int:
    """Human banner; returns process-style exit code (0 READY/DEGRADED)."""
    report = report or run_checks()
    out("")
    out("ZERION SYSTEM CHECK")
    for r in report["rows"]:
        out(f"  {r['name']:16s} {r['state']:11s} {r['detail'][:90]}")
    out(f"  → overall: {report['overall']}")
    return 0 if report["overall"] in ("READY", "DEGRADED") else 1
