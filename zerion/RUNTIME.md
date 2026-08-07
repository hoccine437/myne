# Zerion 24/7 Runtime & Startup Greeting

Two additive Core/runtime features, living in `zerion/runtime/`. Nothing here
modifies the Core: the package composes `config`, `constitution`, `speech`,
`memory`, `knowledge`, `learning`, `phone`, and the `ui` bridge. `main.py` is
Constitution-protected and is not touched; both features are reachable through
`python -m runtime` (service) and `python -m ui.server` (standalone UI).

---

## 1. Startup greeting

When Zerion reaches READY — and only then — it announces itself once:

```
Welcome back. Zerion is online and ready.
```

* Fires only after: config loaded → Core initialized (constitution integrity
  verified) → services initialized → initial health checks pass → READY. It
  can never fire early, and it never fires during a failed start.
* **Voice-first**: delivered through the Core's existing `speech` module when
  `speech_status()` reports ready (Termux / desktop with player). When voice
  is unavailable it falls back to text on the active surface (console, service
  log, UI chat).
* **Configurable**: `ZERION_GREETING` overrides the template; `{name}` is the
  only variable. `ZERION_GREETING_ENABLED=false` disables it entirely.
* **No invented identity**: `{name}` resolves only from the existing profile in
  long-term memory (`memory.identity.name.value`). Unknown stays unknown.
* **Once per startup**: a process-level guard refuses repeats; in service mode
  the UI's own greeting path is also suppressed, so exactly one delivery exists.
* **Non-blocking**: TTS runs on a short-lived daemon thread *after* READY;
  startup never waits on the network.

## 2. 24/7 runtime service

```bash
cd zerion
python -m runtime                    # service + web UI on :8765
python -m runtime --no-ui            # headless
python -m runtime --status           # inspect the live instance
python -m runtime --stop             # graceful stop (SIGTERM)
python -m runtime --check            # one-shot health probe (no lock)
```

### Lifecycle

```
START → acquire instance lock → load config → init Core (integrity!) →
init services (UI/API host, phone, voice) → validate deps → initial health
checks → start background workers → READY → greeting → supervised steady state
```

Startup aborts with a clear exit code if a **critical** check fails
(constitution integrity, API bind). Optional components may start DEGRADED.

### The supervisor loop

One thread, `stop_event.wait(≤1s)` iterations — event-driven idle, ~0% CPU.
Duties are scheduled, not polled: heartbeat every **5s**, health ticks every
**15s**, load-aware maintenance every **15min**, provider reachability every
**5min** (all configurable via `ZERION_*` env, see `runtime/rcfg.py`).

### Health states

Every subsystem is `HEALTHY · DEGRADED · RECOVERING · FAILED · DISABLED`:

| subsystem | probe | recovery |
|---|---|---|
| core *(critical)* | constitution lock + protected-file integrity | none — failure escalates to clean shutdown |
| api *(critical when UI on)* | uvicorn thread + `GET /health` | restart the server thread |
| memory | `load_memory()` (Core self-heals from `.bak`) | re-probe |
| knowledge / learning | SQLite probe queries | re-probe (fresh connections) |
| phone | Termux capability discovery | re-probe (disabled off-Termux) |
| voice | `speech_status()` | re-detect audio player cache |
| model | API key presence + timed reachability | re-probe (heals when network returns) |
| workers | maintenance cadence liveness | run maintenance immediately |

Recovery sequence per failure: detect → log (JSONL) → attempt if safe →
**verify** with an immediate re-probe → HEALTHY, or schedule the next attempt
with **exponential backoff** (2s → 120s cap). After 4 consecutive failed
attempts a subsystem is FAILED; a restart budget (6/window hour) turns a
flapping component perma-FAILED instead of letting it spin. FAILED optional
components are still re-probed at a slow cadence (480s) so external fixes
heal automatically. Overall health is FAILED only if a *critical* subsystem
dies — optional failures never take the Core down.

### Single instance

A `flock`-guarded lock file (`runtime/run/zerion.lock`) owns the instance; a
second start is refused with the existing PID and how to inspect/stop it.
The kernel auto-releases the flock even on SIGKILL — no stale-lock wedging.

### Observability

* `runtime/run/heartbeat.json` — pid, state, uptime, per-subsystem health with
  error details and next-check timing; updated every heartbeat (atomic writes).
* `runtime/run/service.log.jsonl` — structured JSONL, size-rotated; mirrored to
  console for WARNING+. Events: lifecycle, stages, state changes, recovery
  attempts/failures, escalation, maintenance.
* `runtime/run/state.json` — starts counter, last shutdown outcome
  (`clean / unclean / startup_failed`), last uptime. An unclean previous run is
  detected and reported at next start.
* The UI reads the heartbeat read-only via `/api/status` → `runtime` key.

### Shutdown & signals

SIGTERM/SIGINT → graceful: stop API (uvicorn `should_exit`), run cleanup hooks,
final heartbeat, persist `clean` state, release lock, restore handlers.
SIGHUP → revalidate config + force health re-checks. Handlers do minimal work;
the loop does the rest.

### Autostart (explicit, opt-in)

Nothing installs itself. To generate a configuration:

```bash
python -m runtime --install-autostart systemd [--yes]   # user unit + instructions
python -m runtime --install-autostart termux  [--yes]   # ~/.termux/boot/zerion.sh
```

Without `--yes` it prints exactly what it *would* write and changes nothing.
Enabling (`systemctl --user enable --now zerion.service`, or opening Termux
after installing Termux:Boot) is always the user's explicit action.

### Safety

The runtime performs no tool executions and no dispatches: Constitution,
approval gates, Phone Body verification and protected-file rules remain exactly
the Core's, with the same enforcement as interactive mode. The health monitor
*enforces* integrity continuously (the constitution probe re-verifies lock and
protected-file hashes every tick; a tamper escalates to clean shutdown).

## Testing

`tests/test_runtime.py` — 34 tests: greeting (fallback/voice/once/configured/
name-sources/disabled), health monitor (baseline, degrade, recovery-verify,
backoff scheduling, exhaustion, runaway budget, critical escalation, disabled,
external heal, critical-only overall), lockfile (duplicate refusal, stale reap),
structured logger (JSONL + rotation), and full service lifecycle (clean start
→ READY → heartbeat → clean stop, greeting at READY, duplicate instance, startup
failure aborts, live failure+recovery, SIGTERM grace, unclean-previous report,
cleanup hooks, idle stability, UI/API availability, phone states, optional-voice
independence), plus autostart generation.

```bash
python -m pytest tests/test_runtime.py -q
```
