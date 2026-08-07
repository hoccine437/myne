# runtime/__init__.py
"""Zerion long-lived runtime: service lifecycle, health, greeting.

Additive package — it composes the existing Core (config, constitution,
speech, memory, knowledge, learning, phone, ui bridge) and never modifies
it. It is also *not* part of the protected set (see
constitution/constitution.py), so it can evolve freely as long as it
stays additive.

Public surface:

    runtime.service.ZerionService   — the 24/7 supervisor
    runtime.health.HealthMonitor    — subsystem health + recovery
    runtime.lockfile.InstanceLock   — single-instance guard
    runtime.greeting                — startup greeting (voice → text)
    runtime.autostart               — opt-in systemd/Termux configs

CLI:

    cd zerion
    python -m runtime                  # run the service (UI + health)
    python -m runtime --status         # report the running instance
    python -m runtime --stop           # graceful stop of the instance
    python -m runtime --check          # one-shot health check
"""

from runtime.health import HealthMonitor, HealthState, Subsystem  # noqa: F401
from runtime.lockfile import InstanceLock, InstanceLockedError    # noqa: F401
