"""Serialize source upgrades and recovery on the same Vidra install."""
import fcntl
import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def maintenance_lock(root):
    directory = Path(root) / "backups"
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / ".vidra-maintenance.lock"
    with open(path, "a+b") as lock:
        inherited = os.environ.get("VIDRA_MAINTENANCE_LOCK_FD")
        if inherited:
            fd = int(inherited)
            if not os.path.samestat(os.fstat(fd), os.fstat(lock.fileno())):
                raise ValueError("inherited maintenance lock belongs to another install")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield fd
            return
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another backup, restore or source upgrade is active") from exc
        yield lock.fileno()
