"""Only one fliprr may listen at a time (autostart + a manual start = two voices)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import IO


def acquire(path: Path) -> IO | None:
    """Lock ``path``; returns the open handle to keep, or None if another fliprr holds it.

    The OS drops the lock when the process exits, even if it crashes.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+")  # noqa: SIM115 — must stay open while we run
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def is_running(path: Path) -> bool:
    handle = acquire(path)
    if handle is None:
        return True
    handle.close()
    return False
