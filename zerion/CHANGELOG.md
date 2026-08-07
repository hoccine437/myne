# Changelog

## 1.0.0 — entry-point consolidation
- main.py is now the single official door and boots the Web UI by default:
  `python main.py [--host --port]`. A minimal built-in REPL remains via
  `--terminal` for UI-less hosts; missing UI extras degrade to it with a
  clear install hint. terminal.py retired (its surface is absorbed).
- main.py UI path wires SIGTERM→graceful shutdown (uvicorn only handles
  SIGINT itself) and best-effort browser auto-open.
- protected.lock re-locked after the owner-directed main.py change
  (constitution integrity chain intact — verify_lock passes).
- tests/test_entrypoint.py proves: default = UI serving, --terminal REPL,
  --help, graceful shutdown both signals, no duplicated pipeline internals.
- setup.py/docs updated to the new entry contract.

## 1.0.0 — Final release candidate built & verified
- Phone body: phone/device.py host probe (platform/arch/screen/RAM/storage/
  battery/network/sensors, Termux-rich, desktop psutil//proc fallback) +
  tools/device_state_tool.py — the Core knows what it runs on.
- Agents: new agents/ package — five fixed types (researcher/coder/
  verifier/controller/monitor), dynamically instantiated instances,
  resource-bounded pool (capacity from cores+RAM, per-type caps), whitelist
  enforcement (nothing destructive without the supervised path), delegation,
  aggregation, restart budget, reaping; exposed via tools/agent_tools.py.
- Skills: 10 additional routable domain packs (mathematics, physics,
  chemistry, health information, legal information, culinary, languages,
  history, mechanical engineering, writing) + skill_route/skill_list tools;
  legacy four-domain routing preserved byte-for-byte behaviorally.
- Smart brain: cognition/reasoning.py emits multi-path hypothesis scaffolds
  for analytic goals (evidence-led/context-gap/environment-led, bounded,
  revisable, evidence-tagged); confidence stays evidence-bounded (.35–.90).
- Personality: personality.py NORMAL/SERIOUS with real prompt-channel effect
  (persona rules ride reasoning_rules into the model context) + natural
  phrase + slash command switching, persisted in long-term memory; safety
  boundaries explicitly remain active.
- Gemini transport verified offline (mocked): auth, request shape, 401/403,
  429 w/ Retry-After, timeout, network failure, malformed replies; TTS
  payload contract (AUDIO modality, prebuilt voice) + PCM→WAV integrity.
- UI: first-run welcome experience (fast, readiness-driven, skippable).
- second_audit.py: release-gate audit tool (19 checks: integrity, imports,
  secrets, runtime behaviors, service lifecycle, full suite, mobile compat).
- Verification: 157 backend tests, 61 UI smoke checks, full second audit
  PASSED. Gemini audio playback + physical Android execution: NOT VERIFIED
  (no audio hardware / no physical device in the build environment) —
  see FINAL_RELEASE.md for the honest verification matrix.

## Unreleased — Core stabilization pass
- Full-core audit (127 modules) + integration verification: new fenced
  guarantees in tests/test_integration_map.py (every module imports; all
  critical pipeline modules stay reachable from main.py; the documented
  dormant set changes only deliberately) and tests/test_main_integration.py
  (real run_loop E2E over a scripted provider: memory persist+recall, fast
  planner, self-critic, tool routing, confirmation gate, planner, idle
  maintenance, clean exit).
- Relocated .env.example to the package root; removed a leftover extraction
  directory; promoted memory/ to a regular package (additive __init__.py).
- Verified signal-driven shutdown and the multi-threaded memory-writer lock.
- No Core behavior changed; main.py and the constitution corpus are untouched
  (hash-locked). Full suite: 109 passed.

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
