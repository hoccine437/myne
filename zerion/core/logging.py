# core/logging.py
"""
Lightweight leveled, colored logging for Mark-X Lite. Not Python's
stdlib `logging` module (which has meaningful startup cost and a
configuration surface far bigger than this project needs) -- just four
functions and an optional color code, cheap enough to import for free.

Colors are auto-disabled when stdout isn't a real terminal (e.g. piped
output, some Termux contexts) so logs stay readable everywhere.
"""

import os
import sys

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}

_COLORS = {
    "DEBUG": "\033[90m",    # gray
    "INFO": "\033[36m",     # cyan
    "WARNING": "\033[33m",  # yellow
    "ERROR": "\033[31m",    # red
}
_RESET = "\033[0m"

_use_color = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

# Minimum level to actually print. Controlled by LOG_LEVEL env var,
# read lazily (not at import time) so config.py's dotenv loading -- which
# may run after this module is first imported -- still takes effect.
_current_level = None


def _get_level() -> int:
    global _current_level
    if _current_level is None:
        name = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
        _current_level = _LEVELS.get(name, 20)
    return _current_level


def _emit(level: str, message: str) -> None:
    if _LEVELS[level] < _get_level():
        return
    if _use_color:
        print(f"{_COLORS[level]}[{level}]{_RESET} {message}")
    else:
        print(f"[{level}] {message}")


def debug(message: str) -> None:
    _emit("DEBUG", message)


def info(message: str) -> None:
    _emit("INFO", message)


def warning(message: str) -> None:
    _emit("WARNING", message)


def error(message: str) -> None:
    _emit("ERROR", message)
