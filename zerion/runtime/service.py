# runtime/service.py
"""ZerionService — the long-lived 24/7 runtime.

Lifecycle (exactly the mandated sequence):

    START
      → acquire single-instance lock
      → load configuration            (config.validate)
      → initialize Core               (constitution integrity, tools, speech, memory)
      → initialize services           (web API/UI host, phone, voice)
      → validate dependencies         (degrades optional, fails critical)
      → run health checks             (initial probe of every subsystem)
      → start background workers      (bounded idle maintenance cadence)
      → mark READY + greeting         (runtime.greeting, once)
      → long-lived supervised state   (event-driven idle, heartbeat, health ticks)

The supervisor loop is event-driven: one thread, sleeping precisely on
``stop_event.wait(seconds)`` between scheduled duties — never a busy
loop, no polling storms, no extra threads beyond (a) the uvicorn API
host and (b) short-lived greeting TTS. Idle CPU ≈ 0.

Failure policy: every subsystem carries its own probe/recovery contract
in the HealthMonitor (exponential backoff, restart budget, runaway
guard). Optional subsystems may degrade or fail without taking the
service down. A FAILED *critical* subsystem (core integrity) escalates
to a clean shutdown with a clear CRITICAL log — nothing is hidden.

Safety: this module performs no tool execution, no dispatch, no memory
mutation beyond what the Core does itself. Constitution, approval gates
and protected-file rules are entirely the Core's and are untouched.
"""

from __future__ import annotations

import json
import os
import signal
import threading
import time
from enum import Enum

import config
from core import logging as core_log

from runtime import greeting, rcfg
from runtime.health import HealthMonitor, HealthState, Subsystem
from runtime.lockfile import InstanceLock, InstanceLockedError
from runtime.logging import StructuredLogger


class ServiceState(Enum):
    INIT = "init"
    STARTING = "starting"
    READY = "ready"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


# exit codes — stable, scriptable contract
EXIT_OK = 0
EXIT_STARTUP_FAILED = 2
EXIT_ALREADY_RUNNING = 3
EXIT_CRITICAL_FAILURE = 4


def _default_runtime_dir() -> str:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "runtime", "run")


class ZerionService:
    def __init__(self, *, enable_ui: bool = True,
                 ui_host: str | None = None, ui_port: int | None = None,
                 runtime_dir: str | None = None,
                 health_interval: float | None = None,
                 heartbeat_interval: float | None = None,
                 maintenance_interval: float | None = None,
                 network_interval: float | None = None,
                 greet: bool = True,
                 text_channel=None,
                 logger: StructuredLogger | None = None):
        self.runtime_dir = runtime_dir or _default_runtime_dir()
        self.run_dir = self.runtime_dir
        os.makedirs(self.run_dir, exist_ok=True)

        self.enable_ui = enable_ui
        self.ui_host = ui_host or rcfg.UI_HOST
        self.ui_port = ui_port if ui_port is not None else rcfg.UI_PORT
        self.greet = greet
        self.text_channel = text_channel

        self.health_interval = health_interval or rcfg.HEALTH_INTERVAL
        self.heartbeat_interval = heartbeat_interval or rcfg.HEARTBEAT_INTERVAL
        self.maintenance_interval = maintenance_interval or rcfg.MAINTENANCE_INTERVAL
        self.network_interval = network_interval or rcfg.NETWORK_CHECK_INTERVAL

        self.log = logger or StructuredLogger(
            os.path.join(self.run_dir, "service.log.jsonl"))

        self.lock = InstanceLock(os.path.join(self.run_dir, "zerion.lock"))
        self.heartbeat_path = os.path.join(self.run_dir, "heartbeat.json")
        self.state_path = os.path.join(self.run_dir, "state.json")

        self.state = ServiceState.INIT
        self.started_at = None
        self._failed = False
        self._exit_code = EXIT_OK
        self._stop_event = threading.Event()
        self._reload_requested = False
        self._ui_server = None
        self._ui_thread: threading.Thread | None = None
        self._cleanup_hooks: list = []
        self._background = None
        self._last_maintenance = 0.0
        self._last_heartbeat = 0.0
        self._last_health = 0.0
        self._next_network_check = 0.0
        self._bus = None            # set when UI hosted: ui.events.bus
        self._signals_installed = []
        self._original_handlers = {}

        self.monitor = HealthMonitor(
            interval=self.health_interval,
            restart_budget=rcfg.RESTART_BUDGET,
            restart_window=rcfg.RESTART_WINDOW,
            failed_reprobe_factor=rcfg.FAILED_REPROBE_FACTOR,
            logger=self.log,
            on_critical_failure=self._on_critical_failure,
            on_state_change=self._on_subsystem_state_change,
        )

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def start(self) -> int:
        """Run the full lifecycle; returns a process exit code. Blocks in
        the supervisor loop until stopped (signal, stop(), or critical
        escalation)."""
        self.started_at = time.time()
        self.state = ServiceState.STARTING
        self._install_signal_handlers()
        self._log_lifecycle("start.begin", "service starting",
                            {"pid": os.getpid(), "ui": self.enable_ui})

        # --- single instance -------------------------------------------
        try:
            self.lock.acquire()
        except InstanceLockedError as e:
            self.log.error("start.already_running", "service", str(e),
                           {"existing": e.existing})
            return EXIT_ALREADY_RUNNING

        try:
            previous = self._read_state()
            if previous and previous.get("last_shutdown") not in (None, "clean"):
                self.log.warning("start.unclean_previous", "service",
                                 "previous shutdown was not clean "
                                 f"({previous.get('last_shutdown')}); continuing with integrity checks",
                                 {"previous": previous})
            self._mark_state(last_shutdown="unclean", starts=True)  # until proven clean

            # --- load configuration ------------------------------------
            stage_started = time.monotonic()
            warnings = config.validate()
            for w in warnings:
                self.log.info("config.warning", "config", w)
            self._log_stage("config", stage_started)

            # --- initialize Core ----------------------------------------
            ok = self._stage_core()
            if not ok:
                return self._abort_start("core initialization failed")
            self._register_subsystems()

            # --- initialize services ------------------------------------
            if self.enable_ui:
                if not self._stage_ui():
                    return self._abort_start("API/UI service failed to start")
            else:
                self.monitor.disable("api", "UI hosting disabled (--no-ui)")

            # --- validate dependencies + initial health checks ----------
            self.monitor.tick()  # full initial probe of everything enabled
            overall = self.monitor.overall()
            if overall == HealthState.FAILED:
                return self._abort_start(
                    "critical subsystem failed initial health checks — refusing to run")

            # --- background workers begin their cadence ------------------
            self._background_last_run()

            # --- READY ---------------------------------------------------
            self.state = ServiceState.READY
            self._write_heartbeat()
            self._log_lifecycle("start.ready", "Zerion is READY",
                                {"health": overall.value,
                                 "uptime_s": round(time.time() - self.started_at, 2)})
            if self.greet:
                self._deliver_greeting()

            self.state = ServiceState.RUNNING
            self._supervise()
            return self._exit_code
        finally:
            self._shutdown_final()

    def stop(self, reason: str = "stop requested") -> None:
        """Thread-safe graceful shutdown request."""
        if self.state in (ServiceState.STOPPING, ServiceState.STOPPED):
            return
        if self.state == ServiceState.FAILED:
            self._failed = True
            self._exit_code = EXIT_CRITICAL_FAILURE
        self.state = ServiceState.STOPPING
        self.log.info("shutdown.begin", "service", reason)
        self._stop_event.set()

    def register_cleanup(self, hook) -> None:
        self._cleanup_hooks.append(hook)

    # ------------------------------------------------------------------
    # startup stages
    # ------------------------------------------------------------------

    def _stage_core(self) -> bool:
        """Constitution integrity, tool discovery, voice status, memory."""
        stage_started = time.monotonic()
        try:
            from constitution.constitution import ConstitutionEngine
            ConstitutionEngine.load()
        except Exception as e:
            self.log.critical("init.core", "core",
                              f"Constitution integrity check failed: {e}")
            return False
        try:
            from tools.manager import tool_manager
            tools = tool_manager.list_tools()
            self.log.info("init.tools", "core", f"{len(tools)} tools available")
        except Exception as e:
            self.log.warning("init.tools", "core", f"tool discovery degraded: {e}")
        try:
            import speech
            self.log.info("init.voice", "voice", speech.speech_status())
        except Exception as e:
            self.log.warning("init.voice", "voice", f"voice subsystem unavailable: {e}")
        self._log_stage("core", stage_started)
        return True

    def _stage_ui(self) -> bool:
        """Host the WebUI API server (uvicorn) in a daemon thread."""
        stage_started = time.monotonic()
        try:
            import uvicorn
            import ui.server as ui_server

            # The service owns the READY→greeting sequence; the UI module's
            # own startup greeting is for standalone (uvicorn CLI) hosting.
            ui_server.SUPPRESS_STARTUP_GREETING = True

            cfg = uvicorn.Config(
                ui_server.app, host=self.ui_host, port=self.ui_port,
                log_level="warning", loop="asyncio",
            )
            self._ui_server = uvicorn.Server(cfg)
            # Server.run() creates and owns the event loop for this thread —
            # nothing loop-related must be set up from the calling thread.
            self._ui_thread = threading.Thread(
                target=self._ui_server.run, name="zerion-ui", daemon=True)
            self._ui_thread.start()
            # "Initialize services" means *initialized*: bind completes
            # before we return, so the first health tick probes a real
            # service instead of racing uvicorn's startup (and the monitor
            # never "recovers" a component that was healthy all along).
            deadline = time.monotonic() + 8.0
            while not self._ui_server.started and time.monotonic() < deadline:
                if not self._ui_thread.is_alive():
                    break
                time.sleep(0.05)
            if not self._ui_server.started:
                self.log.error("init.api", "api", "UI server did not bind within 8s")
                return False
            self._bus = ui_server.bus
            self._log_stage("api", stage_started, {"port": self.ui_port})
            return True
        except Exception as e:
            self.log.error("init.api", "api", f"UI server failed to start: {e}")
            return False

    def _register_subsystems(self) -> None:
        """Wire the probe/recover contract of every monitored subsystem.
        Probes are local and cheap (they run on every health tick)."""
        svc = self  # probes close over the service

        # --- core integrity (CRITICAL — constitution + protected files) ---
        def probe_core():
            try:
                from constitution.constitution import ConstitutionEngine
                ConstitutionEngine.verify_lock()
                ConstitutionEngine.load()
            except Exception as e:
                return str(e)
            return None
        self.monitor.register(Subsystem(
            "core", probe=probe_core, recover=None, critical=True,
            provenance="constitution.verify_lock + load"))

        # --- API (the hosted web UI server) ---
        def probe_api():
            if not svc._ui_server or not svc._ui_thread or not svc._ui_thread.is_alive():
                return "ui server thread not running"
            if not svc._ui_server.started:
                return "ui server not started yet"
            if svc.ui_port and svc.ui_port > 0:
                try:
                    import requests
                    r = requests.get(f"http://127.0.0.1:{svc.ui_port}/health", timeout=2.0)
                    if r.status_code != 200:
                        return f"health endpoint status {r.status_code}"
                except Exception as e:
                    return f"health endpoint unreachable: {e}"
            return None

        def recover_api():
            try:
                if svc._ui_server:
                    svc._ui_server.should_exit = True
                if svc._ui_thread:
                    svc._ui_thread.join(timeout=3)
            except Exception:
                pass
            return svc._stage_ui()
        self.monitor.register(Subsystem(
            "api", probe=probe_api, recover=recover_api, critical=self.enable_ui,
            enabled=self.enable_ui, provenance="uvicorn thread + /health"))

        # --- memory ---------------------------------------------------
        def probe_memory():
            try:
                from memory.memory_manager import load_memory
                memory = load_memory()
                if not isinstance(memory, dict):
                    return "memory file unreadable"
            except Exception as e:
                return f"memory read failed: {e}"
            return None
        self.monitor.register(Subsystem(
            "memory", probe=probe_memory, recover=None,
            provenance="memory_manager.load_memory (self-heals via .bak)"))

        # --- knowledge / learning (same SQLite store, distinct concerns) ---
        def probe_knowledge():
            try:
                from knowledge.database import Database
                Database().query("SELECT 1 FROM records LIMIT 1")
            except Exception as e:
                return f"knowledge store failed: {e}"
            return None
        self.monitor.register(Subsystem(
            "knowledge", probe=probe_knowledge, recover=None,
            provenance="Database SELECT 1 (fresh connection per call)"))

        def probe_learning():
            try:
                from learning.optimizer import MemoryOptimizer
                MemoryOptimizer().db.query("SELECT count(*) AS n FROM records")
                from learning.retention import RetentionScheduler
                due = RetentionScheduler().due()
                if len(due) > 40:  # bounded: overdue learning items never hide
                    return f"retention backlog ({len(due)} due) — review soon"
            except Exception as e:
                return f"learning store failed: {e}"
            return None
        self.monitor.register(Subsystem(
            "learning", probe=probe_learning, recover=None,
            provenance="MemoryOptimizer query + RetentionScheduler.due()"))

        # --- phone body ---------------------------------------------------
        def _is_termux():
            return "com.termux" in os.environ.get("PREFIX", "")

        def probe_phone():
            try:
                from phone.discovery import CapabilityDiscovery
                caps = CapabilityDiscovery().capabilities()
                available = sum(1 for c in caps if c.available)
                if available == 0:
                    return "no Termux:API capabilities present"
            except Exception as e:
                return f"phone discovery failed: {e}"
            return None
        self.monitor.register(Subsystem(
            "phone", probe=probe_phone, recover=None, enabled=_is_termux(),
            provenance="CapabilityDiscovery (Termux binaries)"))

        # --- voice -------------------------------------------------------
        def probe_voice():
            try:
                import speech
                status = speech.speech_status()
                if status != "Speech: Gemini voice ready.":
                    return status.rstrip(".")
            except Exception as e:
                return f"voice check failed: {e}"
            return None

        def recover_voice():
            # refresh the speech module's cached player detection
            try:
                import speech
                if hasattr(speech, "_player_cmd"):
                    speech._player_cmd = None
                speech._detect_player()
            except Exception:
                return False
            return True
        self.monitor.register(Subsystem(
            "voice", probe=probe_voice, recover=recover_voice,
            enabled=bool(config.VOICE_ENABLED and config.VOICE_PROVIDER == "gemini"),
            provenance="speech_status + player re-detect"))

        # --- model availability ------------------------------------------
        def probe_model():
            if not config.GEMINI_API_KEY:
                return "GEMINI_API_KEY not configured"
            now = time.monotonic()
            if now >= svc._next_network_check:
                svc._next_network_check = now + svc.network_interval
                try:
                    import requests
                    requests.head("https://generativelanguage.googleapis.com/",
                                  timeout=2.5)
                except Exception as e:
                    return f"provider unreachable: {type(e).__name__}"
            return None
        self.monitor.register(Subsystem(
            "model", probe=probe_model, recover=None,
            enabled=True, provenance="API key presence + periodic reachability"))

        # --- workers (maintenance cadence) --------------------------------
        def probe_workers():
            if svc._last_maintenance == 0.0:
                return None  # first run scheduled, not overdue
            overdue = time.monotonic() - svc._last_maintenance
            limit = svc.maintenance_interval * 2 + 60
            if overdue > limit:
                return f"maintenance overdue by {int(overdue - svc.maintenance_interval)}s"
            return None

        def recover_workers():
            svc._run_maintenance()  # run it right now, in-band
            return svc._last_maintenance > 0
        self.monitor.register(Subsystem(
            "workers", probe=probe_workers, recover=recover_workers,
            provenance="idle-maintenance cadence"))

        # --- agents (ecosystem liveness: queue + failure posture) ----------
        def probe_agents():
            try:
                # canonical public surface (agents/__init__.py), the same
                # import shape connectivity_audit + test_orchestrator use
                from agents import agent_pool
                s = agent_pool.stats()
                if s["tracked"] > s["max_pending"]:
                    return f"agent backlog beyond bound ({s['tracked']}/{s['max_pending']})"
                failed_recent = sum(v.get("failed", 0) for v in s["by_type"].values())
                if s["tracked"] and failed_recent > max(4, s["tracked"] // 2):
                    return f"abnormal failure rate ({failed_recent}/{s['tracked']} failed)"
            except Exception as e:
                return f"agent pool probe failed: {e}"
            return None
        self.monitor.register(Subsystem(
            "agents", probe=probe_agents, recover=None,
            provenance="agents.service pool capacity + failure posture"))

        # --- communication layer: connector health, never fatal -------------
        def probe_comm():
            if not config.COMM_ENABLED:
                svc.monitor.subsystems.get("comm")
                return None  # layer disabled by configuration — clean state
            from comms.registry import connectors
            states = connectors.health()
            if not states:
                # no connectors configured: the layer idles, honestly quiet
                return None
            bad = {p: h for p, h in states.items()
                   if h.get("state") == "error"}
            if bad:
                return "connector error(s): " + "; ".join(
                    f"{p}: {h.get('detail', '')[:80]}" for p, h in bad.items())
            return None
        self.monitor.register(Subsystem(
            "comm", probe=probe_comm, recover=None,
            enabled=config.COMM_ENABLED,
            provenance="comms.registry connector health sweep"))

    # ------------------------------------------------------------------
    # supervisor loop — event-driven; one iteration per scheduled duty
    # ------------------------------------------------------------------

    def _supervise(self) -> None:
        while not self._stop_event.is_set():
            now = time.monotonic()

            if self._reload_requested:
                self._reload_requested = False
                self._handle_reload()

            if now - self._last_health >= self.health_interval:
                self._last_health = now
                self.monitor.tick(now)
                overall = self.monitor.overall()
                if overall == HealthState.FAILED:
                    # critical escalation path ran (via callback) — stop()
                    # was already invoked there; this is just belt+braces.
                    self.stop("critical failure")
                    break

            if now - self._last_heartbeat >= self.heartbeat_interval:
                self._last_heartbeat = now
                self._write_heartbeat()

            if now - self._last_maintenance >= self.maintenance_interval:
                self._run_maintenance()

            # sleep until the nearest duty (or shutdown) — no busy loop
            wake = min(self.heartbeat_interval, self.health_interval, 1.0)
            self._stop_event.wait(wake)

    # ------------------------------------------------------------------
    # maintenance (reuses the Core's load-aware BackgroundLearning)
    # ------------------------------------------------------------------

    def _background_last_run(self) -> None:
        from learning.background import BackgroundLearning
        self._background = BackgroundLearning()
        self._last_maintenance = time.monotonic()

    def _run_maintenance(self) -> None:
        try:
            result = self._background.run_once()
            self._last_maintenance = time.monotonic()
            if result:
                self.log.debug("maintenance", "workers", result)
        except Exception as e:
            self._last_maintenance = time.monotonic()
            self.log.warning("maintenance.error", "workers", f"deferred: {e}")
        # communication trigger pump: bounded sweep, no-op without connectors;
        # errors degrade the layer in logs/health only, never the service
        if config.COMM_ENABLED:
            try:
                # autonomy layer: inbound events flow through the full
                # decide→draft→gate→(send|park)→verify lane; workflows fire too
                from comms.autopilot import pump as autopilot_pump
                pulse = autopilot_pump()
                if pulse.get("ingested") or pulse.get("workflows"):
                    self.log.info("comm.poll", "comm",
                                  f"{pulse['ingested']} ingested, "
                                  f"{pulse['workflows']} workflow(s) fired")
            except Exception as e:
                self.log.warning("comm.poll.error", "comm", f"deferred: {e}")

    # ------------------------------------------------------------------
    # reload, escalation, callbacks
    # ------------------------------------------------------------------

    def _handle_reload(self) -> None:
        self.log.info("reload", "service",
                      "reload requested (SIGHUP): re-validating config and forcing health checks")
        for w in config.validate():
            self.log.info("config.warning", "config", w)
        self._last_health = 0.0

    def _on_critical_failure(self, sub: Subsystem) -> None:
        self.state = ServiceState.FAILED
        self._failed = True
        self._failure_kind = self._failure_kind or "critical"
        self.log.critical("escalation", sub.name,
                          f"CRITICAL subsystem failed and cannot recover: {sub.last_error}. "
                          f"Initiating shutdown so nothing runs against an untrusted core.")
        self._exit_code = EXIT_CRITICAL_FAILURE
        self._stop_event.set()

    def _on_subsystem_state_change(self, sub: Subsystem,
                                   old: HealthState, new: HealthState) -> None:
        if self._bus is None:
            return
        level = ("info" if new == HealthState.HEALTHY
                 else "warning" if new in (HealthState.DEGRADED, HealthState.RECOVERING)
                 else "error")
        try:
            self._bus.emit("notification", {
                "level": level,
                "text": f"[{sub.name}] {old.value} → {new.value}"
                        + (f": {sub.last_error}" if sub.last_error else ""),
            })
        except Exception:
            pass

    # ------------------------------------------------------------------
    # greeting
    # ------------------------------------------------------------------

    def _deliver_greeting(self) -> None:
        try:
            from memory.memory_manager import load_memory
            memory = load_memory()
        except Exception:
            memory = None

        def to_channels(text: str) -> None:
            # caller-provided text sink (tests/custom UIs) or the console
            if self.text_channel is not None:
                self.text_channel(text)
            else:
                print(text, flush=True)
            self.log.info("greeting", "service", text)
            if self._bus is not None:
                try:
                    self._bus.emit("chat", {"role": "ai", "text": text, "kind": "system"})
                except Exception:
                    pass

        delivered = greeting.deliver_startup_greeting(
            memory=memory, text_channel=to_channels, blocking=False)
        if delivered and greeting.voice_available():
            # voice path handled audio — also keep a visible copy for text clients
            self.log.info("greeting", "service", delivered, {"voice": True})
            if self._bus is not None:
                try:
                    self._bus.emit("chat", {"role": "ai", "text": delivered, "kind": "system"})
                except Exception:
                    pass
            if self.text_channel is not None:
                self.text_channel(delivered)
            else:
                print(delivered, flush=True)

    # ------------------------------------------------------------------
    # heartbeat, state persistence, shutdown
    # ------------------------------------------------------------------

    def _write_heartbeat(self) -> None:
        hb = {
            "pid": os.getpid(),
            "state": self.state.value,
            "version": self._version(),
            "started_at": self.started_at,
            "uptime_s": round((time.time() - self.started_at), 1) if self.started_at else 0,
            "health": self.monitor.snapshot(),
            "ui": {"enabled": self.enable_ui, "port": self.ui_port} if self.enable_ui else None,
            "ts": time.time(),
        }
        _atomic_write_json(self.heartbeat_path, hb)

    def _read_state(self) -> dict | None:
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _mark_state(self, **updates) -> None:
        state = self._read_state() or {"starts": 0}
        if updates.pop("starts", False):
            state["starts"] = int(state.get("starts", 0)) + 1
        for k, v in updates.items():
            state[k] = v
        state["ts"] = time.time()
        _atomic_write_json(self.state_path, state)

    def _version(self) -> str:
        try:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            with open(os.path.join(base, "VERSION"), "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return "unknown"

    def _abort_start(self, why: str) -> int:
        self.log.critical("start.failed", "service", f"startup aborted: {why}")
        self.state = ServiceState.FAILED
        self._failed = True
        self._failure_kind = "startup"
        return EXIT_STARTUP_FAILED

    def _shutdown_final(self) -> None:
        """Runs exactly once, from start()'s finally: stop services, run
        cleanup hooks, persist state, release the instance lock."""
        self.state = ServiceState.STOPPING
        self._stop_event.set()

        if self._ui_server is not None:
            try:
                self._ui_server.should_exit = True
            except Exception:
                pass
        if self._ui_thread is not None:
            self._ui_thread.join(timeout=6)
            self._ui_thread = None

        for hook in self._cleanup_hooks:
            try:
                hook()
            except Exception as e:
                self.log.warning("cleanup.error", "service", f"cleanup hook failed: {e}")

        clean = not self._failed
        marker = ("clean" if clean
                  else "startup_failed" if self._failure_kind == "startup"
                  else "unclean")
        self.state = ServiceState.STOPPED
        self._mark_state(last_shutdown=marker,
                         last_stop_reason="stopped",
                         last_uptime_s=round(time.time() - self.started_at, 1)
                         if self.started_at else 0)
        self._write_heartbeat()
        self.lock.release()
        self.log.info("shutdown.complete", "service",
                      f"shutdown complete ({'clean' if clean else 'after failure'})")
        self._restore_signal_handlers()

    # ------------------------------------------------------------------
    # signals — handlers only record the request; the loop reacts
    # ------------------------------------------------------------------

    def _install_signal_handlers(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return  # signals only install on the main thread
        for sig, tag in ((signal.SIGTERM, "SIGTERM"), (signal.SIGINT, "SIGINT")):
            try:
                self._original_handlers[sig] = signal.getsignal(sig)
                signal.signal(sig, self._make_signal_handler(tag))
                self._signals_installed.append(sig)
            except (ValueError, OSError):
                pass
        if hasattr(signal, "SIGHUP"):
            try:
                self._original_handlers[signal.SIGHUP] = signal.getsignal(signal.SIGHUP)
                def _hup(signum, frame):
                    self._reload_requested = True
                signal.signal(signal.SIGHUP, _hup)
                self._signals_installed.append(signal.SIGHUP)
            except (ValueError, OSError):
                pass

    def _make_signal_handler(self, tag: str):
        def _handle(signum, frame):
            # minimal work inside the handler — set the flag, keep
            # everything else for the loop
            self.stop(f"signal {tag}")
        return _handle

    def _restore_signal_handlers(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return
        for sig in self._signals_installed:
            try:
                signal.signal(sig, self._original_handlers.get(sig) or signal.SIG_DFL)
            except (ValueError, OSError):
                pass
        self._signals_installed.clear()

    # ------------------------------------------------------------------
    # logging helpers
    # ------------------------------------------------------------------

    def _log_stage(self, stage: str, started_monotonic: float, extra: dict = None) -> None:
        data = {"duration_s": round(time.monotonic() - started_monotonic, 3)}
        if extra:
            data.update(extra)
        self.log.info("stage.done", stage, f"stage '{stage}' complete", data)

    def _log_lifecycle(self, event: str, message: str, data: dict = None) -> None:
        self.log.info(event, "lifecycle", message, data)
        core_log.info(message)


def _atomic_write_json(path: str, payload: dict) -> None:
    tmp = f"{path}.tmp-{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
