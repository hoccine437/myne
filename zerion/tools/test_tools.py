# tools/test_tools.py
"""Bounded test-execution tool for the testing agent.

Runs a pytest target on the nodejs-pool host with the same rlimits +
timeout discipline as exec_tools. Non-destructive by record (pytest writes
.pytest_cache only, gitignored), but reuses execute-boundary conventions:
argument-list invocation, bounded output, hard timeout."""

from __future__ import annotations

import os
import subprocess
import sys

from tools.base import Tool, ToolResult
from tools.exec_tools import _truncate

_TIMEOUT_SECONDS = 120


def _limits():
    if os.name != "posix":
        return None
    def apply():
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (_TIMEOUT_SECONDS, _TIMEOUT_SECONDS + 5))
            resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
        except Exception:
            pass
    return apply


class PytestRunTool(Tool):
    name = "run_pytest"
    description = ("Run the project's test suite (or a given tests/ path) with "
                   "pytest -q. Bounded (120s), rlimited on POSIX. Use to verify "
                   "code after changes.")
    parameters = {"path": "optional test target, default 'tests/'"}
    destructive = False

    def available(self) -> bool:
        import shutil
        return shutil.which("pytest") is not None or True

    def execute(self, parameters: dict) -> ToolResult:
        path = str((parameters or {}).get("path", "tests/")).strip() or "tests/"
        # only test trees allowed
        if os.path.isabs(path) or ".." in path.split("/"):
            return ToolResult.fail(error="invalid_path",
                                   message="only project-relative test paths are allowed")
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        target = os.path.join(root, path)
        if not os.path.exists(target):
            return ToolResult.fail(error="not_found", message=f"no such path: {path}")
        try:
            r = subprocess.run([sys.executable, "-m", "pytest", target, "-q"],
                               capture_output=True, text=True, timeout=_TIMEOUT_SECONDS,
                               cwd=root, preexec_fn=_limits())
            out = _truncate((r.stdout + r.stderr).strip())
            if r.returncode != 0:
                return ToolResult.fail("nonzero_exit", out or f"pytest exited {r.returncode}")
            return ToolResult.ok(data=out, message=out or "(no output)")
        except subprocess.TimeoutExpired:
            return ToolResult.fail("timeout", f"pytest exceeded {_TIMEOUT_SECONDS}s.")
        except OSError as e:
            return ToolResult.fail("execution_failed", str(e))
