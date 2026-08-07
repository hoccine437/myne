# Changelog

## Unreleased — 24/7 runtime + startup greeting (additive layer)
- Added `runtime/` package: long-lived service lifecycle (`python -m runtime`)
  with single-instance flock lockfile, structured JSONL logging with rotation,
  heartbeat + machine-readable status/state files, signal-driven graceful
  shutdown (SIGTERM/SIGINT, SIGHUP reload), resource cleanup hooks, and
  run-state persistence that reports unclean previous runs.
- Added HealthMonitor: per-subsystem probes with HEALTHY/DEGRADED/RECOVERING/
  FAILED/DISABLED states, recovery with immediate verification, per-subsystem
  exponential backoff, restart budget (runaway protection), critical-only
  escalation to clean shutdown, and slow re-probing of FAILED optional
  subsystems so external healing is detected. Monitors: core integrity,
  API/UI host, memory, knowledge, learning, phone, voice, model, workers.
- Added startup greeting: fires once after READY (never during init), voice
  via the existing speech module with text fallback, configurable via
  ZERION_GREETING / ZERION_GREETING_ENABLED, uses the stored profile name only.
- Added explicit opt-in autostart generation (systemd user unit, Termux:Boot
  script); nothing is written without `--yes`.
- The standalone UI server startup now delivers the same READY greeting.
- Added `tests/test_runtime.py` (34 tests). Full suite: 98 passed.

## Unreleased — WebUI (additive layer)
- Added the official Zerion WebUI (`ui/`): an adaptive "AI Operating System"
  workspace — one screen that reshapes itself from Core classification events
  (chat / coding / research / trading / vision / automation workspaces, focus
  mode, live Core orb with per-state animation, system telemetry, agents
  roster, goals/tasks/decisions feeds, terminal through the Core tool policy,
  floating explorer/logs/memory/developer panels, settings incl. runtime Core
  toggles, multi-device smart layout, gestures, monitor pop-out view).
- The UI is a front-end adapter (`ui/session.py` mirrors `main.py`'s turn
  pipeline branch-for-branch; session state imported from `main.py`). No Core
  behavior changed; all state-changing UI actions route through the existing
  engines and the Tool Manager's confirmation flow.
- Added `tests/test_ui_bridge.py` (14 tests) and a headless client smoke test
  (`ui/smoke/smoke.mjs`, 58 checks). Full Core suite remains green.

## 1.0.0-rc.1 — 2026-08-05
- Added Constitution integrity and protected-core checks.
- Added staged evolution protection, backup, versioning and rollback.
- Added knowledge, experience, reflection, capability and runtime intelligence records.
- Added provider dispatch adapter and persistent local health store.
- Added supervised phone parameter extraction and dispatch contract.
- Added optional offline voice adapter for Piper or Termux TTS.
- Hardened execution: removed `shell=True`; added bounded isolated Python execution.
- Added regression tests for Constitution, memory, execution, provider dispatch, voice, phone, capability and intelligence paths.
