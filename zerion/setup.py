# setup.py
"""Idempotent first-run preparation for Zerion.

Provisions everything the final product needs, in layers:

  Core   (always):  requests, python-dotenv
  UI     (default): fastapi, uvicorn[standard], psutil  → ui/requirements-ui.txt

Pure-Python everywhere the Core runs. On Termux, the UI extras compile small
native pieces (uvloop/httptools/pydantic-core, psutil) — install the C/Rust
toolchain first if pip reports build failures:  pkg install clang make rust

Safe to re-run: each step checks before acting (.env preserved, packages
verified by import, not by pkg list). Nothing here enables autostart or
touches OS configuration — autostart is a separate explicit command
(`python -m runtime --install-autostart ... --yes`).

CLI:
  python setup.py            # core + UI extras
  python setup.py --no-ui    # core only (lightest possible install)
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# module name → pip requirement. Checked by import (idempotent), installed
# from the matching requirements file.
CORE_REQUIRED = {"requests": "requests", "dotenv": "python-dotenv"}
UI_REQUIRED = {"fastapi": "fastapi", "uvicorn": "uvicorn[standard]", "psutil": "psutil"}

REQUIRED_DIRS = (
    "memory", "constitution", "providers", "tools", "skills", "agents",
    "phone", "runtime", "ui", "tests",
)
REQUIRED_FILES = ("main.py", "config.py", "prompt.txt", "VERSION", ".env.example")


def termux() -> bool:
    return "com.termux" in os.environ.get("PREFIX", "")


def missing_packages(required: dict) -> list:
    return [pkg for module, pkg in required.items() if importlib.util.find_spec(module) is None]


def ensure_packages(install: bool = True, ui: bool = True) -> dict:
    """Install what's missing (idempotent) and import-verify afterwards.
    Returns {layer: [still-missing packages]} — empty lists mean OK."""
    result = {}
    layers = [("core", CORE_REQUIRED, ROOT / "requirements.txt")]
    if ui:
        layers.append(("ui", UI_REQUIRED, ROOT / "ui" / "requirements-ui.txt"))
    for layer, required, req_file in layers:
        missing = missing_packages(required)
        if missing and install:
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req_file)],
                           check=False)
        result[layer] = missing_packages(required)
    return result


def ensure_env() -> str:
    path = ROOT / ".env"
    if not path.exists():
        path.write_text(
            "LLM_PROVIDER=gemini\nGEMINI_API_KEY=replace_with_key\n"
            "GEMINI_MODEL=gemini-3-flash-lite\nVOICE_ENABLED=true\n"
            "VOICE_PROVIDER=gemini\nVOICE_NAME=Charon\n",
            encoding="utf8")
        return "created"
    return "preserved"


def verify_imports(ui: bool = True) -> list:
    """Post-install import sanity across the load-bearing surfaces."""
    surfaces = ["config", "speech", "tools.manager", "memory.memory_manager",
                "knowledge.manager", "intent.engine", "planner", "phone.engine",
                "agents", "skills.manager", "personality", "runtime.service"]
    if ui:
        surfaces.append("ui.server")
    failed = []
    for mod in surfaces:
        try:
            __import__(mod)
        except Exception as e:
            failed.append(f"{mod}: {type(e).__name__}")
    return failed


def run(argv=None) -> int:
    args = set((argv or sys.argv)[1:])
    want_ui = "--no-ui" not in args
    print("Zerion setup")
    print("Python:", sys.version.split()[0],
          "OK" if sys.version_info >= (3, 10) else "UNSUPPORTED (need 3.10+)")
    if sys.version_info < (3, 10):
        return 2

    pkgs = ensure_packages(ui=want_ui)
    for layer, missing in pkgs.items():
        print(f"{layer.title()} packages:", "OK" if not missing else "missing: " + ", ".join(missing))
    if pkgs["core"]:
        print("  → core packages failed to install; Zerion cannot start without them.")
        return 2

    env = ensure_env()
    print(".env:", env)

    missing_dirs = [d for d in REQUIRED_DIRS if not (ROOT / d).is_dir()]
    print("Project structure:", "OK" if not missing_dirs else "missing: " + ", ".join(missing_dirs))
    missing_files = [f for f in REQUIRED_FILES if not (ROOT / f).exists()]
    if missing_files:
        print("Project files: missing:", ", ".join(missing_files))

    writable = os.access(ROOT, os.W_OK)
    print("Project writable:", writable)

    try:
        from constitution.constitution import ConstitutionEngine
        print("Constitution integrity:", ConstitutionEngine.verify_lock())
    except Exception as exc:
        print("Constitution integrity: FAILED -", exc)
        return 3

    failed = verify_imports(ui=want_ui)
    print("Import sanity:", "OK" if not failed else "FAILED: " + "; ".join(failed))

    print("Platform:", "Termux" if termux() else "non-Termux")
    commands = ["termux-media-player", "termux-battery-status", "termux-clipboard-get",
                "termux-telephony-call"]
    available = [x for x in commands if shutil.which(x)]
    print("Termux API commands:", ", ".join(available) if available else "none (optional)")

    players = [x for x in ("mpv", "ffplay", "aplay", "paplay", "termux-media-player") if shutil.which(x)]
    print("Audio player for voice output:", ", ".join(players) if players else "none found (voice output needs one)")

    print()
    print("Next:")
    print("  python main.py                  # official entry — Web UI by default (--terminal = REPL)")
    if want_ui and not pkgs.get("ui"):
        print("  python -m ui.server --port 8765 # browser UI")
        print("  python -m runtime               # 24/7 service (hosts UI)")
    print("  python -m runtime --check       # one-shot health check")
    print("  python -m pytest tests/ -q      # full test suite")
    print()
    print("Setup complete. Configure GEMINI_API_KEY in .env for Gemini text and speech.")
    return 0 if not failed else 3


if __name__ == "__main__":
    raise SystemExit(run())
