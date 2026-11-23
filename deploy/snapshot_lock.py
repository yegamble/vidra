"""Serialize maintenance operations on one Vidra installation."""
import fcntl
import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path


def _open_lock(root):
    root = Path(root)
    directory = root / "backups"
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        pass
    else:
        # A manual root backup must not lock the normal deploy user out of the
        # following timer run. Only adjust an entry we have just created.
        if os.geteuid() == 0:
            owner = root.stat()
            os.chown(directory, owner.st_uid, owner.st_gid, follow_symlinks=False)
    path = directory / ".vidra-maintenance.lock"
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        fd = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        fd = os.open(path, flags)
    else:
        if os.geteuid() == 0:
            try:
                owner = directory.stat()
                os.fchown(fd, owner.st_uid, owner.st_gid)
            except OSError:
                os.close(fd)
                raise
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError("expected a regular Vidra maintenance lock file")
    return os.fdopen(fd, "r+b")


@contextmanager
def maintenance_lock(root):
    inherited = os.environ.get("VIDRA_MAINTENANCE_LOCK_FD")
    # Check the borrowed descriptor before allocating ours: a stale descriptor
    # number could otherwise be reassigned to the newly opened lock and pass.
    borrowed = os.fstat(int(inherited)) if inherited else None
    with _open_lock(root) as lock:
        fd = int(inherited) if borrowed else lock.fileno()
        if borrowed and not os.path.samestat(borrowed, os.fstat(lock.fileno())):
            raise ValueError("inherited maintenance lock belongs to another install")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another backup, restore or upgrade is active on this install") from exc
        yield fd


if __name__ == "__main__":
    try:
        with maintenance_lock(sys.argv[1]):
            # A shell lends us its open file description. The kernel keeps the
            # flock for the shell's lifetime after this validating child exits.
            pass
    except (OSError, ValueError) as exc:
        sys.exit("vidra maintenance: " + str(exc))
