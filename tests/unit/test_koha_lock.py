# SPDX-License-Identifier: MIT-0
import importlib.util
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
PACKAGE = "ansible_collections.jmz.koha.plugins.module_utils"


def load_modules():
    names = ["ansible_collections", "ansible_collections.jmz", "ansible_collections.jmz.koha",
             "ansible_collections.jmz.koha.plugins", PACKAGE]
    fakes = {name: types.ModuleType(name) for name in names}
    with mock.patch.dict(sys.modules, fakes):
        loaded = {}
        for name in ("koha_instance", "koha_lock"):
            spec = importlib.util.spec_from_file_location("%s.%s" % (PACKAGE, name),
                                                          os.path.join(ROOT, "plugins/module_utils/%s.py" % name))
            module = importlib.util.module_from_spec(spec)
            sys.modules["%s.%s" % (PACKAGE, name)] = module
            spec.loader.exec_module(module)
            loaded[name] = module
    return loaded


class KohaLockTest(unittest.TestCase):
    def setUp(self):
        loaded = load_modules()
        self.lock = loaded["koha_lock"]
        self.error = loaded["koha_instance"].ModuleInputError
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(self.lock, "LOCK_DIR", self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_second_holder_fails_immediately_and_the_lock_is_reusable_afterwards(self):
        with self.lock.exclusive_lock("instance", "biblioteca", "ocupado"):
            with self.assertRaisesRegex(self.error, "ocupado"):
                with self.lock.exclusive_lock("instance", "biblioteca", "ocupado"):
                    pass
        with self.lock.exclusive_lock("instance", "biblioteca", "ocupado"):
            pass

    def test_different_scopes_and_names_do_not_collide(self):
        with self.lock.exclusive_lock("instance", "a", "x"):
            with self.lock.exclusive_lock("instance", "b", "x"):
                with self.lock.exclusive_lock("localization", "a", "x"):
                    pass

    def test_lock_is_released_when_the_body_raises(self):
        with self.assertRaises(RuntimeError):
            with self.lock.exclusive_lock("instance", "a", "x"):
                raise RuntimeError("boom")
        with self.lock.exclusive_lock("instance", "a", "x"):
            pass

    def test_waiting_acquires_the_lock_once_the_holder_lets_go(self):
        release = threading.Event()
        held = threading.Event()

        def holder():
            with self.lock.exclusive_lock("translate", "global", "x"):
                held.set()
                release.wait(5)

        thread = threading.Thread(target=holder)
        thread.start()
        self.assertTrue(held.wait(5))
        threading.Timer(0.3, release.set).start()
        started = time.monotonic()
        with self.lock.exclusive_lock("translate", "global", "ocupado", wait=5):
            waited = time.monotonic() - started
        thread.join()
        self.assertGreaterEqual(waited, 0.2)

    def test_waiting_gives_up_at_the_deadline(self):
        with self.lock.exclusive_lock("translate", "global", "x"):
            started = time.monotonic()
            with self.assertRaisesRegex(self.error, "agotó"):
                with self.lock.exclusive_lock("translate", "global", "se agotó la espera", wait=0.3):
                    pass
            self.assertGreaterEqual(time.monotonic() - started, 0.25)


if __name__ == "__main__":
    unittest.main()
