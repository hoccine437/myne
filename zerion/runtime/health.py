# runtime/health.py
"""Subsystem health monitoring with recovery, backoff and runaway guards.

Each registered subsystem periodically gets ``probe()``'d (cheap, local,
never blocking for long) on the service's supervisor tick:

    probe() returns None/""  → subsystem is HEALTHY
    probe() returns a string → that string is the failure reason
    probe() raises           → treated as failure (reason = exception)

On failure the monitor follows the required sequence — log, decide if
recovery is safe, attempt it, verify the probe again, return to HEALTHY
or advance toward FAILED — with per-subsystem exponential backoff and a
restart budget, so a flapping component can never spin the machine.

A subsystem without a ``recover`` action (e.g. "model" when only the API
key is wrong) degrades to DEGRADED and keeps being re-probed: external
conditions can heal without any action on our side. Critical subsystems
(only "core" today) escalate through ``on_critical_failure``; nothing
optional is ever allowed to take the service down.

The clock is injectable (``now=``) so tests exercise backoff and budgets
without sleeping.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


class HealthState(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    RECOVERING = "recovering"
    FAILED = "failed"
    DISABLED = "disabled"


@dataclass
class Subsystem:
    name: str
    probe: Callable[[], Optional[str]]
    recover: Optional[Callable[[], bool]] = None
    critical: bool = False
    enabled: bool = True
    max_recovery_attempts: int = 4
    base_backoff: float = 2.0     # seconds, doubles per failure
    max_backoff: float = 120.0
    provenance: str = ""

    # runtime state (not constructor args)
    state: HealthState = field(default=HealthState.HEALTHY)
    consecutive_failures: int = 0
    recovery_attempts: int = 0          # total, ever
    recovery_timestamps: list = field(default_factory=list)
    last_error: str = ""
    last_change: float = 0.0            # wall clock of last state change
    next_check: float = 0.0             # monotonic time when next probe is due
    checks: int = 0

    def backoff_after(self, failures: int) -> float:
        return min(self.base_backoff * (2 ** max(failures - 1, 0)), self.max_backoff)


class HealthMonitor:
    def __init__(self, *, now: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time,
                 interval: float = 15.0,
                 restart_budget: int = 6, restart_window: float = 3600.0,
                 failed_reprobe_factor: int = 4,
                 logger=None,
                 on_critical_failure: Optional[Callable[[Subsystem], None]] = None,
                 on_state_change: Optional[Callable[[Subsystem, HealthState, HealthState], None]] = None):
        self._now = now
        self._wall = wall
        self.interval = interval
        self.restart_budget = restart_budget
        self.restart_window = restart_window
        self.failed_reprobe_factor = failed_reprobe_factor
        self.log = logger
        self.on_critical_failure = on_critical_failure
        self.on_state_change = on_state_change
        self.subsystems: dict[str, Subsystem] = {}

    # ------------------------------------------------------------------
    # registration
    # ------------------------------------------------------------------

    def register(self, subsystem: Subsystem) -> Subsystem:
        subsystem.last_change = self._wall()
        subsystem.next_check = self._now()
        if not subsystem.enabled:
            subsystem.state = HealthState.DISABLED
        self.subsystems[subsystem.name] = subsystem
        return subsystem

    def disable(self, name: str, reason: str = "disabled by configuration") -> None:
        sub = self.subsystems.get(name)
        if sub is None:
            return
        self._transition(sub, HealthState.DISABLED, reason)

    def set_enabled(self, name: str, enabled: bool, reason: str = "") -> None:
        sub = self.subsystems.get(name)
        if sub is None:
            return
        sub.enabled = enabled
        if not enabled:
            self._transition(sub, HealthState.DISABLED, reason or "disabled")
        elif sub.state == HealthState.DISABLED:
            sub.state = HealthState.HEALTHY
            sub.next_check = self._now()

    # ------------------------------------------------------------------
    # the tick — called by the supervisor loop
    # ------------------------------------------------------------------

    def tick(self, now: float = None) -> None:
        now = self._now() if now is None else now
        for sub in self.subsystems.values():
            if sub.state == HealthState.DISABLED:
                continue
            if now < sub.next_check:
                continue
            self._check(sub, now)

    def force_check(self, name: str) -> None:
        sub = self.subsystems.get(name)
        if sub and sub.state != HealthState.DISABLED:
            self._check(sub, self._now())

    def _check(self, sub: Subsystem, now: float) -> None:
        sub.checks += 1
        reason = self._probe_safe(sub)

        if not reason:
            self._on_success(sub, now)
            return

        # ---- failure path: detect → log → recover-safe? → attempt → verify
        sub.consecutive_failures += 1
        sub.last_error = reason
        self._log("WARNING", "subsystem.failure", sub.name, reason,
                  {"failures": sub.consecutive_failures})

        # Runaway guard: too many recovery attempts in the window → FAILED.
        if self._over_restart_budget(sub):
            self._transition(sub, HealthState.FAILED,
                             f"restart budget exceeded ({self.restart_budget} per "
                             f"{int(self.restart_window)}s): {reason}")
            sub.next_check = now + sub.max_backoff * self.failed_reprobe_factor
            return

        if sub.critical and sub.recover is None:
            self._transition(sub, HealthState.FAILED, f"critical failure: {reason}")
            return

        if sub.recover is None:
            # Nothing safe to do — stay DEGRADED and keep watching.
            if sub.state != HealthState.RECOVERING:
                self._transition(sub, HealthState.DEGRADED, reason)
            else:
                self._log("INFO", "recovery.gave_up_no_action", sub.name,
                          "no recovery action available; remaining DEGRADED")
                self._transition(sub, HealthState.DEGRADED, reason)
            sub.next_check = now + sub.backoff_after(sub.consecutive_failures)
            return

        if sub.consecutive_failures > sub.max_recovery_attempts:
            self._transition(sub, HealthState.FAILED,
                             f"recovery attempts exhausted ({sub.max_recovery_attempts}): {reason}")
            sub.next_check = now + sub.max_backoff * self.failed_reprobe_factor
            return

        # attempt recovery
        was_recovering = sub.state == HealthState.RECOVERING
        if not was_recovering:
            self._transition(sub, HealthState.RECOVERING, reason)
        sub.recovery_attempts += 1
        sub.recovery_timestamps.append(self._wall())
        sub.recovery_timestamps = [t for t in sub.recovery_timestamps
                                   if self._wall() - t < self.restart_window]
        self._log("INFO", "recovery.attempt", sub.name,
                  f"attempt {sub.recovery_attempts}: {reason}")

        try:
            recovered = bool(sub.recover())
        except Exception as exc:
            recovered = False
            self._log("WARNING", "recovery.error", sub.name, f"recovery raised: {exc}")

        # verify recovery with an immediate re-probe
        verify_reason = None
        if recovered:
            verify_reason = self._probe_safe(sub)

        if recovered and not verify_reason:
            self._transition(sub, HealthState.HEALTHY, "recovery verified")
            sub.consecutive_failures = 0
            sub.next_check = now + self.interval
        else:
            detail = verify_reason or "recovery action reported failure"
            sub.last_error = detail
            delay = sub.backoff_after(sub.consecutive_failures)
            sub.next_check = now + delay
            self._log("WARNING", "recovery.retry_scheduled", sub.name,
                      f"still failing: {detail}; next attempt in {delay:.0f}s")

    # ------------------------------------------------------------------
    # state views
    # ------------------------------------------------------------------

    def overall(self) -> HealthState:
        states = [s.state for s in self.subsystems.values()]
        if any(s.critical and s.state == HealthState.FAILED for s in self.subsystems.values()):
            return HealthState.FAILED
        if any(st in (HealthState.FAILED, HealthState.DEGRADED, HealthState.RECOVERING)
               for st in states):
            return HealthState.DEGRADED
        return HealthState.HEALTHY

    def snapshot(self) -> dict:
        now = self._now()
        out = {}
        for name, sub in self.subsystems.items():
            out[name] = {
                "state": sub.state.value,
                "critical": sub.critical,
                "failures": sub.consecutive_failures,
                "recovery_attempts": sub.recovery_attempts,
                "last_error": sub.last_error or None,
                "checks": sub.checks,
                "next_check_in": max(0.0, round(sub.next_check - now, 1))
                if sub.state != HealthState.DISABLED else None,
                "provenance": sub.provenance,
            }
        return {
            "overall": self.overall().value,
            "subsystems": out,
            "ts": self._wall(),
        }

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _probe_safe(self, sub: Subsystem) -> Optional[str]:
        try:
            result = sub.probe()
        except Exception as exc:
            return f"probe exception: {exc}"
        if result in (None, "", False):
            return None
        return str(result)[:400]

    def _on_success(self, sub: Subsystem, now: float) -> None:
        if sub.state in (HealthState.RECOVERING, HealthState.DEGRADED, HealthState.FAILED):
            self._transition(sub, HealthState.HEALTHY,
                             "probe passes again" if sub.consecutive_failures else "healthy")
        sub.consecutive_failures = 0
        sub.last_error = ""
        sub.next_check = now + self.interval

    def _over_restart_budget(self, sub: Subsystem) -> bool:
        window_start = self._wall() - self.restart_window
        recent = [t for t in sub.recovery_timestamps if t >= window_start]
        return len(recent) >= self.restart_budget

    def _transition(self, sub: Subsystem, new_state: HealthState, reason: str) -> None:
        old = sub.state
        if old == new_state:
            return
        sub.state = new_state
        sub.last_change = self._wall()
        level = ("INFO" if new_state == HealthState.HEALTHY
                 else "WARNING" if new_state in (HealthState.DEGRADED, HealthState.RECOVERING)
                 else "ERROR" if new_state == HealthState.FAILED
                 else "DEBUG")
        self._log(level, "subsystem.state_change", sub.name,
                  f"{old.value} → {new_state.value}: {reason}")
        if self.on_state_change:
            try:
                self.on_state_change(sub, old, new_state)
            except Exception:
                pass
        if new_state == HealthState.FAILED and sub.critical and self.on_critical_failure:
            try:
                self.on_critical_failure(sub)
            except Exception:
                pass

    def _log(self, level: str, event: str, component: str, message: str, data: dict = None) -> None:
        if self.log is not None:
            try:
                self.log.log(level, event, component, message, data)
            except Exception:
                pass
