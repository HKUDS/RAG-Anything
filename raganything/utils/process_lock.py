"""Cross-platform file locking for process mutual exclusion.

Provides a :class:`FileLock` that works on both Windows (``msvcrt.locking``)
and Unix (``fcntl.flock``). Locks are automatically released when the owning
process exits — even on crash — because the OS tracks them by file descriptor.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional


class FileLock:
    """Exclusive, non-blocking, cross-platform file lock.

    Usage as context manager::

        with FileLock("/path/to/file.lock") as acquired:
            if acquired:
                ...  # we hold the lock
            else:
                ...  # another process holds it

    Usage as manual acquire/release::

        lock = FileLock("/path/to/file.lock")
        if lock.acquire():
            try:
                ...
            finally:
                lock.release()

    Locks are **advisory** (Unix) or **mandatory through byte-range**
    (Windows). In both cases the OS guarantees the lock is released when
    the owning process exits, so a crash never leaves a zombie lock.
    """

    def __init__(self, lock_path: str):
        self._lock_path = Path(lock_path)
        self._fd: Optional[int] = None
        self._file = None  # Python file object (kept alive for fd lifetime)

    # ── public API ──────────────────────────────────────

    def acquire(self, timeout: float = 0) -> bool:
        """Try to acquire the exclusive lock (non-blocking by default).

        Args:
            timeout: Seconds to wait. **0** means non-blocking (return
                     immediately). Values > 0 are accepted for API
                     compatibility but not yet implemented — they behave
                     like 0 (non-blocking).

        Returns:
            ``True`` if the lock was acquired, ``False`` if another
            process holds it.
        """
        if self._fd is not None:
            return True  # already held by this instance

        self._lock_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            fd = os.open(str(self._lock_path), os.O_CREAT | os.O_RDWR)
            if sys.platform == "win32":
                import msvcrt
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                except (OSError, IOError):
                    os.close(fd)
                    return False
            else:
                import fcntl
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except (OSError, IOError):
                    os.close(fd)
                    return False

            self._fd = fd
            # Keep a Python file handle so GC doesn't close the fd early
            self._file = os.fdopen(fd, "r+", closefd=False)
            return True
        except Exception:
            if self._fd is not None:
                try:
                    os.close(self._fd)
                except Exception:
                    pass
                self._fd = None
            raise

    def release(self) -> None:
        """Release the lock. Safe to call multiple times."""
        fd = self._fd
        self._fd = None
        if self._file is not None:
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None
        if fd is not None:
            try:
                # On Unix, closing the fd releases the flock automatically.
                # On Windows, closing the fd also releases the byte-range lock.
                os.close(fd)
            except Exception:
                pass

    def is_locked(self) -> bool:
        """Check if *this instance* currently holds the lock.

        Note: this does **not** test whether *any* process holds the lock
        — only whether ``acquire()`` succeeded on this instance.
        """
        return self._fd is not None

    # ── context manager ─────────────────────────────────

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()
        return False  # don't suppress exceptions


# ── convenience helpers ──────────────────────────────────────────────

def get_lock_dir(working_dir: str | Path) -> Path:
    """Return the canonical lock directory for a working directory."""
    return Path(working_dir) / ".locks"


def get_file_lock_path(working_dir: str | Path, file_hash: str) -> Path:
    """Build the lock file path for a document identified by hash."""
    return get_lock_dir(working_dir) / f"{file_hash}.lock"


def get_server_pid_path(working_dir: str | Path) -> Path:
    """Build the path to the server PID file."""
    return Path(working_dir) / ".server.pid"
