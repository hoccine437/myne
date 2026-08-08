# runtime/__main__.py
"""Zerion 24/7 runtime CLI.

    python -m runtime                          # start the service (foreground daemon)
    python -m runtime --no-ui                  # service without the web UI
    python -m runtime --ui-port 9000           # service hosts UI on port 9000
    python -m runtime --status                 # inspect a running instance
    python -m runtime --stop                   # gracefully stop it
    python -m runtime --check                  # one-shot health probe, no lock
    python -m runtime --install-autostart systemd [--yes]
    python -m runtime --install-autostart termux  [--yes]

The service intentionally runs in the foreground: process supervisors
(systemd, Termux:Boot, Docker, ...) own daemonization, restart policies
and logging capture far better than a double-fork ever could inside the
process.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time

# Core modules import package-less from the zerion/ directory.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

from runtime.lockfile import InstanceLock  # noqa: E402
from runtime.service import (ZerionService, _default_runtime_dir,  # noqa: E402
                             EXIT_ALREADY_RUNNING, EXIT_OK)


def _status(runtime_dir: str) -> int:
    hb_path = os.path.join(runtime_dir, "heartbeat.json")
    lock = InstanceLock(os.path.join(runtime_dir, "zerion.lock"))
    existing = lock.existing_instance()

    hb = None
    try:
        with open(hb_path, "r", encoding="utf-8") as f:
            hb = json.load(f)
    except Exception:
        pass

    if existing is None and hb is None:
        print("Zerion service is not running (no lock, no heartbeat).")
        return 3
    if existing is None and hb is not None:
        print(f"Zerion service is NOT running. Last heartbeat at {hb.get('ts')}, "
              f"state={hb.get('state')}.")
        print(json.dumps(hb.get("health", {}), indent=1))
        return 3

    print(f"Zerion service is RUNNING (pid {existing.get('pid')}, "
          f"started {time.ctime(existing.get('started_at', 0))}).")
    if hb:
        print(f"  state: {hb.get('state')}  uptime: {hb.get('uptime_s')}s  "
              f"overall health: {hb.get('health', {}).get('overall')}")
        for name, sub in (hb.get("health", {}).get("subsystems") or {}).items():
            err = f"  last error: {sub['last_error']}" if sub.get("last_error") else ""
            print(f"  - {name:10s} {sub.get('state', '?'):10s} checks={sub.get('checks', 0)}{err}")
    return 0


def _stop(runtime_dir: str) -> int:
    lock = InstanceLock(os.path.join(runtime_dir, "zerion.lock"))
    existing = lock.existing_instance()
    if not existing or not existing.get("pid"):
        print("No running Zerion instance found.")
        return 3
    pid = int(existing["pid"])
    print(f"Stopping Zerion service (pid {pid})…")
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as e:
        print(f"Could not signal pid {pid}: {e}")
        return 1
    deadline = time.time() + 15
    while time.time() < deadline:
        if lock.existing_instance() is None:
            print("Stopped cleanly.")
            return 0
        time.sleep(0.25)
    print("Instance did not stop within 15s — it may be wedged; "
          "inspect before using SIGKILL.")
    return 1


def _check() -> int:
    """One-shot health probe + the ZERION SYSTEM CHECK matrix."""
    from runtime.selfcheck import run_checks
    report = run_checks()
    print("\nZERION SYSTEM CHECK")
    for r in report["rows"]:
        print(f"  {r['name']:16s} {r['state']:11s} {r['detail'][:90]}")
    svc = ZerionService(enable_ui=False, greet=False)
    # --check shouldn't claim the instance lock: probe directly
    svc._stage_core()
    svc._register_subsystems()
    svc.monitor.tick()
    snap = svc.monitor.snapshot()
    print(f"overall: {snap['overall']}")
    for name, sub in snap["subsystems"].items():
        mark = {"healthy": "✓", "degraded": "!", "failed": "✗",
                "recovering": "…", "disabled": "-"}.get(sub["state"], "?")
        err = f" — {sub['last_error']}" if sub.get("last_error") else ""
        print(f" {mark} {name:10s} {sub['state']:10s}{err}")
    failed = report["overall"] == "FAILED" or snap["overall"] not in ("healthy", "degraded")
    return 1 if failed else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="zerion-runtime",
                                     description="Zerion 24/7 runtime service")
    parser.add_argument("--no-ui", action="store_true", help="run without the web UI")
    parser.add_argument("--ui-host", default=None, help="UI bind host (default 0.0.0.0)")
    parser.add_argument("--ui-port", type=int, default=None, help="UI bind port (default 8765)")
    parser.add_argument("--runtime-dir", default=None,
                        help="override runtime state directory (default runtime/run)")
    parser.add_argument("--no-greeting", action="store_true",
                        help="skip the startup greeting")
    parser.add_argument("--status", action="store_true", help="inspect running instance")
    parser.add_argument("--stop", action="store_true", help="gracefully stop running instance")
    parser.add_argument("--check", action="store_true", help="one-shot health probe")
    parser.add_argument("--install-autostart", choices=["systemd", "termux"], default=None,
                        help="generate an autostart configuration")
    parser.add_argument("--yes", action="store_true",
                        help="confirm writing the autostart file (autostart is always explicit)")
    args = parser.parse_args(argv)

    runtime_dir = args.runtime_dir or _default_runtime_dir()

    if args.status:
        return _status(runtime_dir)
    if args.stop:
        return _stop(runtime_dir)
    if args.check:
        return _check()
    if args.install_autostart:
        from runtime import autostart
        report = autostart.install(args.install_autostart, BASE_DIR,
                                   confirmed=args.yes, out=print)
        if report.get("path") and not report["wrote"]:
            print("Re-run with --yes to write the file. Nothing was changed.")
        return 0

    try:
        service = ZerionService(
            enable_ui=not args.no_ui,
            ui_host=args.ui_host, ui_port=args.ui_port,
            runtime_dir=runtime_dir,
            greet=not args.no_greeting,
        )
    except (KeyboardInterrupt, SystemExit):
        return 130

    try:
        code = service.start()
    except KeyboardInterrupt:
        code = EXIT_OK
    if code == EXIT_ALREADY_RUNNING:
        return EXIT_ALREADY_RUNNING
    return code


if __name__ == "__main__":
    raise SystemExit(main())
