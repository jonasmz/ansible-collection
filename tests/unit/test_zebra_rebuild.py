# SPDX-License-Identifier: MIT-0
"""Unit tests for zebra_rebuild; Koha commands and system state are mocked."""

import importlib.util
import os
import sys
import types
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


class ModuleExit(Exception):
    def __init__(self, result):
        self.result = result


class FakeAnsibleModule:
    params = {}
    check_mode = False
    runner = None
    last = None

    def __init__(self, **kwargs):
        defaults = {"instance": "biblioteca", "mode": "incremental", "target": "all", "force": False,
                    "verbose": 1, "quiet": False, "verify_search_engine": True,
                    "require_zebra_running": False, "command_path": "/usr/sbin/koha-rebuild-zebra"}
        defaults.update(type(self).params)
        self.params = defaults
        self.check_mode = type(self).check_mode
        self.commands = []
        type(self).last = self

    def get_bin_path(self, name, required=False):
        return {"koha-list": "/usr/sbin/koha-list", "koha-rebuild-zebra": "/usr/sbin/koha-rebuild-zebra",
                "koha-shell": "/usr/sbin/koha-shell", "koha-zebra": "/usr/sbin/koha-zebra"}.get(name)

    def run_command(self, argv, **kwargs):
        self.commands.append(argv)
        return type(self).runner(argv)

    def exit_json(self, **kwargs):
        raise ModuleExit(kwargs)

    def fail_json(self, **kwargs):
        kwargs.setdefault("failed", True)
        raise ModuleExit(kwargs)


def load_module():
    ansible = types.ModuleType("ansible")
    ansible_utils = types.ModuleType("ansible.module_utils")
    basic = types.ModuleType("ansible.module_utils.basic")
    basic.AnsibleModule = FakeAnsibleModule
    path = os.path.join(ROOT, "plugins/modules/zebra_rebuild.py")
    spec = importlib.util.spec_from_file_location("zebra_rebuild_test", path)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"ansible": ansible, "ansible.module_utils": ansible_utils,
                                      "ansible.module_utils.basic": basic}):
        spec.loader.exec_module(module)
    return module


class ZebraRebuildTest(unittest.TestCase):
    def setUp(self):
        FakeAnsibleModule.params = {}
        FakeAnsibleModule.check_mode = False
        self.module = load_module()
        patches = [
            mock.patch.object(self.module.os.path, "isdir", return_value=True),
            mock.patch.object(self.module.os.path, "isfile", return_value=True),
            mock.patch.object(self.module.os, "access", return_value=True),
            mock.patch.object(self.module.os, "geteuid", return_value=0),
            mock.patch.object(self.module.pwd, "getpwnam", return_value=object()),
            mock.patch.object(self.module.grp, "getgrnam", return_value=object()),
            mock.patch("builtins.open", mock.mock_open(read_data='USE_INDEXER_DAEMON="no"\n')),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_module(self, *, engine="Zebra", zebra=True, result_text="Processing selected indexes\n", rc=0,
                   fail_target=None, help_text=None):
        help_text = help_text or "--full --biblios --authorities --force --verbose --quiet --help"
        def runner(argv):
            if argv[0].endswith("koha-list"):
                return 0, "biblioteca\narchivo\n", ""
            if argv[0].endswith("koha-rebuild-zebra") and "--help" in argv:
                return 0, help_text, ""
            if argv[0].endswith("koha-shell"):
                return 0, engine + "\n", ""
            if argv[0].endswith("koha-zebra"):
                return (0, "Zebra running for instance biblioteca", "") if zebra else (3, "Zebra not running for instance biblioteca", "")
            if argv[0].endswith("koha-rebuild-zebra"):
                target = "biblios" if "--biblios" in argv else "authorities"
                if fail_target == target:
                    return 0, "", "Something went wrong rebuilding %s indexes for biblioteca" % ("biblio" if target == "biblios" else "authority")
                return rc, result_text, ""
            return 0, "", ""
        FakeAnsibleModule.runner = runner
        with self.assertRaises(ModuleExit) as raised:
            self.module.main()
        return raised.exception.result, FakeAnsibleModule.last.commands

    def test_target_and_mode_arguments(self):
        for target, expected_flag in (("biblios", "--biblios"), ("authorities", "--authorities"), ("all", None)):
            FakeAnsibleModule.params = {"target": target}
            result, commands = self.run_module()
            rebuilds = [c for c in commands if c[0].endswith("koha-rebuild-zebra") and "--help" not in c]
            self.assertEqual(len(rebuilds), 2 if target == "all" else 1)
            if expected_flag:
                self.assertIn(expected_flag, rebuilds[0])
            self.assertEqual(result["status"], "completed")
        for target in ("biblios", "authorities", "all"):
            FakeAnsibleModule.params = {"mode": "full", "target": target, "verbose": 0}
            _, commands = self.run_module()
            rebuilds = [c for c in commands if c[0].endswith("koha-rebuild-zebra") and "--help" not in c]
            self.assertTrue(all("--full" in c for c in rebuilds))

    def test_force_and_option_validation(self):
        FakeAnsibleModule.params = {"force": True}
        result, commands = self.run_module()
        self.assertTrue(any("--force" in c for c in commands))
        self.assertTrue(result["changed"])
        FakeAnsibleModule.params = {"mode": "full", "force": True}
        result, commands = self.run_module()
        self.assertIn("only valid", result["msg"])
        self.assertEqual(commands, [])
        FakeAnsibleModule.params = {"quiet": True}
        self.assertIn("conflicts", self.run_module()[0]["msg"])
        FakeAnsibleModule.params = {"quiet": True, "verbose": 0}
        result, commands = self.run_module()
        self.assertTrue(any("--quiet" in c for c in commands))
        FakeAnsibleModule.params = {"verbose": 3}
        _, commands = self.run_module()
        rebuild = [c for c in commands if "--help" not in c and c[0].endswith("koha-rebuild-zebra")][0]
        self.assertEqual(rebuild.count("--verbose"), 3)

    def test_instance_engine_permissions_and_zebra_checks(self):
        FakeAnsibleModule.params = {"instance": "../x"}
        result, _ = self.run_module()
        self.assertIn("instance must", result["msg"])
        FakeAnsibleModule.params = {"verify_search_engine": True}
        result, _ = self.run_module(engine="Elasticsearch")
        self.assertIn("SearchEngine is Elasticsearch", result["msg"])
        FakeAnsibleModule.params = {"require_zebra_running": True}
        result, _ = self.run_module(zebra=False)
        self.assertIn("Zebra is not running", result["msg"])
        with mock.patch.object(self.module.os, "geteuid", return_value=1000):
            result, _ = self.run_module()
        self.assertIn("become: true", result["msg"])

    def test_incremental_daemon_skip_force_and_check_mode(self):
        with mock.patch.object(self.module, "inspect_indexer_configuration", return_value="enabled_or_unset"):
            result, commands = self.run_module()
        self.assertEqual(result["status"], "skipped")
        self.assertFalse(result["changed"])
        self.assertFalse(any("--biblios" in c or "--authorities" in c for c in commands))
        FakeAnsibleModule.params = {"force": True}
        with mock.patch.object(self.module, "inspect_indexer_configuration", return_value="enabled_or_unset"):
            result, commands = self.run_module()
        self.assertEqual(result["status"], "completed")
        self.assertTrue(any("--force" in c for c in commands))
        FakeAnsibleModule.check_mode = True
        FakeAnsibleModule.params = {"mode": "full", "target": "biblios"}
        result, commands = self.run_module()
        self.assertTrue(result["changed"])
        self.assertFalse(result["executed"])
        self.assertTrue(result["command"])
        self.assertFalse(any("--full" in c for c in commands))

    def test_nonzero_internal_error_partial_and_unknown_results(self):
        result, _ = self.run_module(rc=4)
        self.assertTrue(result["failed"])
        self.assertTrue(result["changed"])
        result, _ = self.run_module(fail_target="biblios")
        self.assertTrue(result["failed"])
        self.assertEqual(result["target_results"]["biblios"]["status"], "failed")
        self.assertEqual(result["target_results"]["authorities"]["status"], "completed")
        result, _ = self.run_module(fail_target="authorities")
        self.assertTrue(result["failed"])
        self.assertEqual(result["target_results"]["biblios"]["status"], "completed")
        self.assertEqual(result["target_results"]["authorities"]["status"], "failed")
        result, _ = self.run_module(result_text="")
        self.assertTrue(result["failed"])
        self.assertEqual(result["status"], "unknown")
        result, _ = self.run_module(result_text="Skipped bibliographic indexing because work is unavailable")
        self.assertEqual(result["status"], "skipped")
        self.assertFalse(result["changed"])
        self.assertTrue(result["skipped"])

    def test_lock_warnings_and_cli_compatibility(self):
        result, _ = self.run_module(result_text="Could not obtain lock; another rebuild is active")
        self.assertTrue(result["failed"])
        self.assertEqual(result["status"], "blocked")
        result, _ = self.run_module(result_text="Continuing without lock")
        self.assertEqual(result["status"], "blocked")
        FakeAnsibleModule.params = {"mode": "full"}
        result, _ = self.run_module(help_text="--full --biblios --authorities --help")
        self.assertIn("does not advertise required option --verbose", result["msg"])

    def test_missing_instance_command_and_engine_query_fail_closed(self):
        with mock.patch.object(self.module.os.path, "isdir", return_value=False):
            result, _ = self.run_module()
        self.assertIn("does not exist", result["msg"])
        FakeAnsibleModule.runner = lambda argv: (0, "archivo\n", "")
        with self.assertRaises(ModuleExit) as raised:
            self.module.main()
        self.assertIn("koha-list did not confirm", raised.exception.result["msg"])
        with mock.patch.object(FakeAnsibleModule, "get_bin_path", autospec=True,
                               side_effect=lambda obj, name, required=False: None if name == "koha-rebuild-zebra" else
                               {"koha-list": "/usr/sbin/koha-list"}.get(name)):
            FakeAnsibleModule.runner = lambda argv: (0, "biblioteca\n", "")
            with self.assertRaises(ModuleExit) as raised:
                self.module.main()
        self.assertIn("koha-rebuild-zebra was not found", raised.exception.result["msg"])
        FakeAnsibleModule.params = {"verify_search_engine": True}
        def bad_preference(argv):
            if argv[0].endswith("koha-list"):
                return 0, "biblioteca\n", ""
            if argv[0].endswith("koha-rebuild-zebra"):
                return 0, "--full --biblios --authorities --force --verbose --quiet", ""
            if argv[0].endswith("koha-shell"):
                return 1, "", "database unavailable"
            return 0, "", ""
        FakeAnsibleModule.runner = bad_preference
        with self.assertRaises(ModuleExit) as raised:
            self.module.main()
        self.assertIn("Unable to reliably read SearchEngine", raised.exception.result["msg"])

    def test_authority_only_internal_failure_and_full_check_mode(self):
        FakeAnsibleModule.params = {"target": "authorities"}
        result, _ = self.run_module(fail_target="authorities")
        self.assertEqual(result["target_results"]["authorities"]["status"], "failed")
        self.assertEqual(result["target_results"]["biblios"]["status"], "unknown")
        for mode in ("incremental", "full"):
            FakeAnsibleModule.params = {"mode": mode, "target": "all", "verbose": 0}
            FakeAnsibleModule.check_mode = True
            result, commands = self.run_module()
            self.assertTrue(result["changed"])
            self.assertFalse(result["executed"])
            self.assertTrue(all(not ("--biblios" in command or "--authorities" in command)
                                for command in commands))
            FakeAnsibleModule.check_mode = False

    def test_custom_path_and_dynamic_indexer_setting_fail_safely(self):
        FakeAnsibleModule.params = {"command_path": "/opt/koha/bin/koha-rebuild-zebra", "verbose": 0}
        result, commands = self.run_module()
        self.assertEqual(result["command"][0][0], "/opt/koha/bin/koha-rebuild-zebra")
        FakeAnsibleModule.params = {"verbose": 0}
        with mock.patch.object(self.module, "inspect_indexer_configuration",
                               side_effect=self.module.RebuildError("dynamic setting")):
            result, _ = self.run_module()
        self.assertIn("dynamic setting", result["msg"])

    def test_repeated_imperative_invocations_run_each_time(self):
        first, commands1 = self.run_module()
        second, commands2 = self.run_module()
        self.assertTrue(first["changed"])
        self.assertTrue(second["changed"])
        self.assertEqual(len([c for c in commands1 if "--help" not in c and c[0].endswith("koha-rebuild-zebra")]), 2)
        self.assertEqual(len([c for c in commands2 if "--help" not in c and c[0].endswith("koha-rebuild-zebra")]), 2)

    def test_instances_are_scoped_and_results_are_structured(self):
        FakeAnsibleModule.params = {"instance": "archivo", "target": "biblios", "verbose": 0}
        result, commands = self.run_module()
        rebuilds = [c for c in commands if c[0].endswith("koha-rebuild-zebra") and "--help" not in c]
        self.assertEqual(len(rebuilds), 1)
        self.assertEqual(rebuilds[0][-1], "archivo")
        for key in ("instance", "mode", "target", "status", "executed", "skipped", "skip_reason",
                    "command", "rc", "duration", "search_engine", "zebra_running", "target_results", "stdout", "stderr", "msg"):
            self.assertIn(key, result)
        self.assertIsNone(result["target_results"]["biblios"]["records_processed"])


if __name__ == "__main__":
    unittest.main()
