#!/data/data/com.termux/files/usr/bin/bash
# Zerion Android/Termux launcher. No desktop browser, X11, or Node runtime
# is required; the normal path opens the Web UI in Android's browser when
# termux-open-url is available, and terminal mode is always available.
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

if [ "${1:-}" = "--setup" ]; then
  shift
  python setup.py
fi

if [ "${ZERION_ANDROID_TERMINAL:-0}" = "1" ]; then
  exec python main.py --terminal "$@"
fi

exec python main.py "$@"
