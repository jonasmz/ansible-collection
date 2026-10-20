# SPDX-License-Identifier: MIT-0
"""Per-instance advisory lock shared by the modules that mutate a Koha instance."""

import contextlib
import fcntl
import os

from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import ModuleInputError


LOCK_DIR = "/run/lock"


@contextlib.contextmanager
def exclusive_lock(scope, name, busy_message):
    """Hold a non-blocking exclusive flock on ``<scope>-<name>``; raise ``ModuleInputError`` if taken.

    The lock is released when the descriptor closes, including when the process dies.
    """
    path = os.path.join(LOCK_DIR, "ansible-koha-%s-%s.lock" % (scope, name))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ModuleInputError(busy_message)
        yield
    finally:
        os.close(fd)
