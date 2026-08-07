# runtime/autostart.py
"""Explicit, user-driven autostart configuration.

This module generates service/autostart configuration files for the
current platform. It deliberately does NOT enable, activate or schedule
anything on its own:

* systemd (desktop/Linux): writes a *user* unit to
  ``~/.config/systemd/user/zerion.service`` and prints the exact
  ``systemctl --user enable --now zerion.service`` command for the user
  to run themselves.
* Termux (Android): writes ``~/.termux/boot/zerion.sh`` (used by the
  Termux:Boot companion app) with a wake-lock and the service start
  command. Nothing starts until the user installs/allows Termux:Boot.

Writing any file requires the caller's explicit confirmation flag.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SERVICE_DESCRIPTION = "Zerion AI Runtime"


def systemd_unit(zerion_dir: str, python: str = None, extra_args: str = "") -> str:
    python = python or sys.executable
    return f"""[Unit]
Description={SERVICE_DESCRIPTION}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={zerion_dir}
ExecStart={python} -m runtime {extra_args}
Restart=on-failure
RestartSec=10
# Runaway protection: at most 4 restarts per minute at the manager level;
# Zerion's own health monitor applies per-subsystem backoff inside the
# process before systemd ever needs to step in.
StartLimitBurst=4
StartLimitIntervalSec=60
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
"""


def termux_boot_script(zerion_dir: str, python: str = "python3") -> str:
    return f"""#!/data/data/com.termux/files/usr/bin/sh
# Zerion 24/7 runtime — Termux:Boot entry point.
# Installed explicitly by the user via: python -m runtime --install-autostart termux
termux-wake-lock
cd {zerion_dir}
exec {python} -m runtime
"""


def install(target: str, zerion_dir: str, *, confirmed: bool, out=None) -> dict:
    """Generate the autostart artifact for ``target``. Returns a report:
    {target, path, wrote, instructions}. When ``confirmed`` is False the
    artifact is described but not written."""
    print_fn = out or (lambda *a: None)
    target = (target or "").strip().lower()
    zerion_dir = os.path.abspath(zerion_dir)

    if target == "systemd":
        path = Path.home() / ".config" / "systemd" / "user" / "zerion.service"
        content = systemd_unit(zerion_dir)
        instructions = (f"Wrote {path}\n"
                        f"Review it, then enable explicitly:\n"
                        f"  systemctl --user daemon-reload\n"
                        f"  systemctl --user enable --now zerion.service\n"
                        f"Stop/disable later with: systemctl --user disable --now zerion.service")
    elif target == "termux":
        path = Path.home() / ".termux" / "boot" / "zerion.sh"
        content = termux_boot_script(zerion_dir)
        instructions = (f"Wrote {path}\n"
                        f"Requires the Termux:Boot app. The script runs when you\n"
                        f"next open Termux after boot (or run it yourself). The wake\n"
                        f"lock is held while Zerion runs and released on exit.")
    else:
        return {"target": target, "path": None, "wrote": False,
                "instructions": f"Unsupported autostart target {target!r}. "
                                f"Supported: systemd, termux."}

    report = {"target": target, "path": str(path), "wrote": False,
              "instructions": instructions, "content": content}

    if not confirmed:
        print_fn(f"[autostart] --yes not given; NOT writing {path}")
        print_fn(f"[autostart] would write:\n{content}")
        return report

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if target == "termux":
        path.chmod(0o755)
    report["wrote"] = True
    print_fn(instructions)
    return report
