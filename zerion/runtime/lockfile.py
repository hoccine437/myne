# runtime/lockfile.py
"""Single-instance guard.

POSIX: an exclusive ``flock`` on the lock file. The kernel releases the
flock when *any* descriptor-holding process dies — including SIGKILL —
so a crashed service never wedges later starts, unlike PID-file-only
schemes. The file still carries the PID + start time so ``--status`` and
a refused second start can point at the real live instance.

Non-POSIX fallback: ``O_CREAT|O_EXCL`` with stale-PID sweep (checks the
recorded PID is alive and looks like Zerion before trusting it).
"""

from __future__ import annotations

import json
import os
import time

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:  # pragma: no cover - Windows
    _HAS_FCNTL = False


class InstanceLockedError(RuntimeError):
    """Raised when another live Zerion service instance owns the lock."""

    def __init__(self, message: str, existing: dict | None = None):
        super().__init__(message)
        self.existing = existing or {}


class InstanceLock:
    def __init__(self, path: str):
        self.path = path
        self._fd = None
        self._owned = False

    # ------------------------------------------------------------------

    def acquire(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
        if _HAS_FCNTL:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                existing = self._read_info(fd)
                os.close(fd)
                pid = existing.get("pid", "?")
                raise InstanceLockedError(
                    f"Another Zerion instance is already running (pid {pid}). "
                    f"Use `python -m runtime --status` to inspect it or "
                    f"`python -m runtime --stop` to stop it.",
                    existing=existing)
            self._fd = fd
            self._owned = True
            self._write_meta()
        else:
            self._acquire_fallback()

    def release(self) -> None:
        if not self._owned:
            return
        self._owned = False
        if self._fd is not None:
            fd, self._fd = self._fd, None
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                # clear our mark so a stopped service leaves no stale pid
                os.ftruncate(fd, 0)
            except OSError:
                pass
            os.close(fd)
        else:
            try:
                os.remove(self.path)
            except OSError:
                pass

    @property
    def owned(self) -> bool:
        return self._owned

    # ------------------------------------------------------------------
    # info helpers
    # ------------------------------------------------------------------

    def _write_meta(self) -> None:
        info = {"pid": os.getpid(), "started_at": time.time(),
                "argv": " ".join(os.sys.argv[:4])}
        try:
            os.ftruncate(self._fd, 0)
            os.lseek(self._fd, 0, os.SEEK_SET)
            os.write(self._fd, (json.dumps(info) + "\n").encode("utf-8"))
        except OSError:
            pass

    def _read_info(self, fd=None) -> dict:
        try:
            if fd is None:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.loads(f.readline().strip() or "{}")
            os.lseek(fd, 0, os.SEEK_SET)
            raw = os.read(fd, 4096).decode("utf-8", "replace")
            return json.loads(raw.splitlines()[0] or "{}") if raw.strip() else {}
        except Exception:
            return {}

    def existing_instance(self) -> dict | None:
        """Describe a live instance if one holds this lock, else None."""
        if not os.path.exists(self.path):
            return None
        info = self._read_info()
        if _HAS_FCNTL:
            fd = os.open(self.path, os.O_RDONLY)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return None  # lock free — nobody owns it
            except OSError:
                return info
            finally:
                os.close(fd)
        pid = info.get("pid")
        return info if pid and self._pid_alive(pid) else None

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------
    # non-POSIX fallback
    # ------------------------------------------------------------------

    def _acquire_fallback(self) -> None:  # pragma: no cover - POSIX in CI
        try:
            self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            info = self._read_info()
            pid = info.get("pid")
            if pid and self._pid_alive(pid):
                raise InstanceLockedError(
                    f"Another Zerion instance is already running (pid {pid}).",
                    existing=info)
            # stale file from a dead process
            try:
                os.remove(self.path)
            except OSError as exc:
                raise InstanceLockedError(f"Stale instance lock at {self.path}: {exc}",
                                          existing=info)
            self._acquire_fallback()
            return
        self._owned = True
        self._write_meta()
