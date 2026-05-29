"""Per-profile lock files so two running instances can't share (and clobber)
the same save. The lock lives inside the profile's own folder and holds the
owning PID; a lock whose PID is no longer alive is treated as stale and
ignored."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from cookiebot.config import profile_dir, sanitize_profile

log = logging.getLogger(__name__)


def _lock_path(profile: str) -> Path:
    return profile_dir(profile) / "instance.lock"


def _pid_alive(pid: int) -> bool:
    """True if a process with this PID currently exists."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)  # signal 0 only checks existence/permission
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    return True


def lock_owner(profile: str) -> int | None:
    """PID of the live process holding this profile's lock, or None if free.
    A stale lock (dead PID) is removed and treated as free."""
    path = _lock_path(profile)
    if not path.exists():
        return None
    try:
        pid = int(path.read_text().strip() or "0")
    except (ValueError, OSError):
        pid = 0
    if pid and _pid_alive(pid):
        return pid
    # Stale: clean it up so the profile is usable again.
    try:
        path.unlink()
    except OSError:
        pass
    return None


def is_locked(profile: str) -> bool:
    return lock_owner(profile) is not None


class ProfileLock:
    """Context manager that acquires a profile lock for this process.

    Raises ``ProfileInUseError`` if another live process already holds it.
    """

    def __init__(self, profile: str) -> None:
        self.profile = profile
        self.path = _lock_path(profile)
        self._held = False

    def acquire(self) -> None:
        owner = lock_owner(self.profile)
        if owner is not None:
            raise ProfileInUseError(self.profile, owner)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # O_CREAT|O_EXCL makes creation atomic — if two instances race here,
        # exactly one wins and the other gets FileExistsError.
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise ProfileInUseError(self.profile, lock_owner(self.profile) or -1)
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        self._held = True
        log.info("locked profile %r (pid %d)", self.profile, os.getpid())

    def release(self) -> None:
        if not self._held:
            return
        # Only remove the lock if it's still ours.
        if self._is_our_file():
            try:
                self.path.unlink()
            except OSError:
                pass
        self._held = False

    def _is_our_file(self) -> bool:
        try:
            return int(self.path.read_text().strip() or "0") == os.getpid()
        except (ValueError, OSError):
            return False

    def __enter__(self) -> "ProfileLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


class ProfileInUseError(Exception):
    def __init__(self, profile: str, pid: int) -> None:
        self.profile = profile
        self.pid = pid
        super().__init__(f"profile {profile!r} is in use by pid {pid}")
