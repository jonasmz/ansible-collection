# SPDX-License-Identifier: MIT-0
"""Per-instance advisory lock shared by the modules that mutate a Koha instance."""

import contextlib
import fcntl
import os
import time

from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import ModuleInputError


LOCK_DIR = "/run/lock"


@contextlib.contextmanager
def exclusive_lock(scope, name, busy_message, wait=0):
    """Hold an exclusive flock on ``<scope>-<name>``; raise ``ModuleInputError`` if it stays taken.

    With ``wait`` seconds the lock is retried until the deadline; otherwise it fails at once. The lock
    is released when the descriptor closes, including when the process dies.
    """
    path = os.path.join(LOCK_DIR, "ansible-koha-%s-%s.lock" % (scope, name))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ModuleInputError(busy_message)
                time.sleep(0.1)
        yield
    finally:
        os.close(fd)
