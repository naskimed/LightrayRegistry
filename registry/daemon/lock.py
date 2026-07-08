"""Exclusive daemon lock — fcntl flock with the pid inside; a second daemon fails fast.
Week-1 check: verify flock semantics on the actual mount (overlay/NFS vary)."""
from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager

from .. import config


@contextmanager
def registry_flock():
    path = config.lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise SystemExit(f"registry.lock is held (another daemon/CLI writer is live): {path}")
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        os.fsync(fd)
        yield
    finally:
        try:
            fcntl.lockf(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
