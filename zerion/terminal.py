# terminal.py
"""
Terminal-only interface for Mark-X Lite.

Replaces the original Tkinter GUI with plain stdin/stdout. Exposes the
same minimal surface the assistant loop needs (write_log, start_speaking,
stop_speaking, get_input) so the rest of the code doesn't need to know
the UI changed.

Hardening in this pass: colored role-tagged output (auto-disabled when
not a real TTY, or via NO_COLOR, same convention as core/logging.py), a
brief typing indicator while waiting on a slow LLM call, and a clear
status line for interruptions -- all while staying dependency-free
(stdlib `sys`/`time` only) and cheap enough for Termux.
"""

import sys
import time

import speech

_use_color = sys.stdout.isatty() and __import__("os").environ.get("NO_COLOR") is None

_AI_COLOR = "\033[32m"    # green
_USER_COLOR = "\033[36m"  # cyan
_DIM = "\033[90m"
_RESET = "\033[0m"


def _colorize(text: str, color: str) -> str:
    return f"{color}{text}{_RESET}" if _use_color else text


class TerminalUI:
    def write_log(self, text: str) -> None:
        """Print an assistant message. Text already carries its own
        'AI: ' prefix from main.py in most call sites; this just colors
        that prefix when present so output stays readable without
        forcing every caller to know about color codes."""
        if text.startswith("AI:"):
            prefix = _colorize("AI:", _AI_COLOR)
            print(f"{prefix}{text[3:]}")
        else:
            print(text)

    def start_speaking(self) -> None:
        """Brief 'thinking...' indicator while waiting on a slow call.
        Purely cosmetic -- never blocks, never required for correctness,
        and costs nothing when stdout isn't a real terminal."""
        if _use_color:
            print(_colorize("...", _DIM), end="\r")
            sys.stdout.flush()

    def stop_speaking(self) -> None:
        if _use_color:
            print(" " * 10, end="\r")  # clear the indicator line
            sys.stdout.flush()

    def get_input(self, prompt: str = "You: ") -> str:
        """
        Get one line of user input. Tries speech first (if enabled and
        available), falls back to the keyboard otherwise. Ctrl+C/Ctrl+D
        during input are treated as a clean 'exit', not a crash.
        """
        text = speech.listen()
        if text:
            print(f"{_colorize('You (voice):', _USER_COLOR)} {text}")
            return text

        colored_prompt = _colorize(prompt, _USER_COLOR) if _use_color else prompt
        try:
            return input(colored_prompt)
        except (EOFError, KeyboardInterrupt):
            print()  # move off the partial input line before "Goodbye."
            return "exit"
