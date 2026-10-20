# SPDX-License-Identifier: MIT-0
import importlib.util
import os
import sys
import types
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
PACKAGE = "ansible_collections.jmz.koha.plugins.module_utils"


class ModuleExit(Exception):
    def __init__(self, result):
        self.result = result


class FakeAnsibleModule:
    params = {}
    check_mode = False

    def __init__(self, **kwargs):
        self.params = dict(type(self).params)
        self.check_mode = type(self).check_mode

    def exit_json(self, **kwargs):
        raise ModuleExit(kwargs)

    def fail_json(self, **kwargs):
        raise ModuleExit(dict(kwargs, failed=True))


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_modules():
    names = ["ansible", "ansible.module_utils", "ansible.module_utils.basic", "ansible_collections",
             "ansible_collections.jmz", "ansible_collections.jmz.koha", "ansible_collections.jmz.koha.plugins", PACKAGE]
    fakes = {name: types.ModuleType(name) for name in names}
    fakes["ansible.module_utils.basic"].AnsibleModule = FakeAnsibleModule
    with mock.patch.dict(sys.modules, fakes):
        helper = _load("plugins/module_utils/koha_instance.py", PACKAGE + ".koha_instance")
        util = _load("plugins/module_utils/mariadb_timezone.py", PACKAGE + ".mariadb_timezone")
        module = _load("plugins/modules/mariadb_timezone.py", "mariadb_timezone_module_test")
    return helper, util, module


class Runner:
    """Fake AnsibleModule that answers the MariaDB client calls."""

    def __init__(self, known_after=1, binaries=("mariadb", "mariadb-tzinfo-to-sql", "systemctl")):
        self.commands = []
        self.queries = 0
        self.known_after = known_after
        self.binaries = binaries

    def get_bin_path(self, name, required=False):
        return "/usr/bin/" + name if name in self.binaries else None

    def run_command(self, argv, **kwargs):
        self.commands.append((argv, kwargs))
        if "--execute" in argv:
            self.queries += 1
            return 0, "1\n" if self.queries >= self.known_after else "0\n", ""
        if argv[0].endswith("tzinfo-to-sql"):
            return 0, "INSERT INTO mysql.time_zone_name VALUES (...);", ""
        return 0, "", ""


class MariadbTimezoneTest(unittest.TestCase):
    def setUp(self):
        self.helper, self.util, self.module = load_modules()
        patcher = mock.patch.object(self.util.os.path, "isfile", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_tables_are_loaded_when_missing(self):
        runner = Runner(known_after=2)
        self.assertTrue(self.util.ensure_mariadb_timezone(runner, "America/Argentina/Buenos_Aires", "localhost"))
        self.assertEqual(runner.queries, 2)
        self.assertTrue(any(argv[-2:] == ["restart", "mariadb"] for argv, _ in runner.commands))

    def test_nothing_happens_when_mariadb_already_knows_the_zone(self):
        runner = Runner(known_after=1)
        self.assertFalse(self.util.ensure_mariadb_timezone(runner, "America/Argentina/Buenos_Aires", "localhost"))
        self.assertEqual(len(runner.commands), 1)

    def test_apply_false_reports_without_mutating(self):
        runner = Runner(known_after=99)
        self.assertTrue(self.util.ensure_mariadb_timezone(runner, "America/Argentina/Buenos_Aires", "localhost", apply=False))
        self.assertEqual(len(runner.commands), 1)

    def test_system_and_offsets_need_no_tables(self):
        for zone in ("SYSTEM", "-03:00", ""):
            self.assertFalse(self.util.ensure_mariadb_timezone(Runner(), zone, "localhost"))

    def test_remote_database_is_refused(self):
        with self.assertRaisesRegex(self.helper.ModuleInputError, "base remota"):
            self.util.ensure_mariadb_timezone(Runner(), "America/Argentina/Buenos_Aires", "db.example.org")

    def run_module(self, check_mode=False, **params):
        FakeAnsibleModule.params = dict({"timezone": "America/Argentina/Buenos_Aires", "dbhost": "localhost"}, **params)
        FakeAnsibleModule.check_mode = check_mode
        with mock.patch.object(self.module.os, "geteuid", return_value=0), \
             mock.patch.object(self.module, "ensure_mariadb_timezone", return_value=True) as ensure:
            with self.assertRaises(ModuleExit) as raised:
                self.module.main()
        return raised.exception.result, ensure

    def test_module_applies_and_reports_change(self):
        result, ensure = self.run_module()
        self.assertTrue(result["changed"])
        self.assertTrue(ensure.call_args.kwargs["apply"])

    def test_module_check_mode_does_not_apply(self):
        result, ensure = self.run_module(check_mode=True)
        self.assertTrue(result["changed"])
        self.assertFalse(ensure.call_args.kwargs["apply"])

    def test_module_requires_root(self):
        FakeAnsibleModule.params = {"timezone": "America/Argentina/Buenos_Aires", "dbhost": "localhost"}
        with mock.patch.object(self.module.os, "geteuid", return_value=1000):
            with self.assertRaises(ModuleExit) as raised:
                self.module.main()
        self.assertIn("become", raised.exception.result["msg"])


if __name__ == "__main__":
    unittest.main()
