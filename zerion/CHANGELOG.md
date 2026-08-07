# Changelog

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
