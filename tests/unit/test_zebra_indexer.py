# SPDX-License-Identifier: MIT-0
"""Unit tests for zebra_indexer using isolated command and filesystem mocks."""

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
    last = None

    def __init__(self, **kwargs):
        self.params = {"command_path": "/usr/sbin/koha-indexer", "quiet": False,
                       "verify_zebra_engine": False, "require_zebra_running": False, **type(self).params}
        self.check_mode = type(self).check_mode
        self.commands = []
        self.runner = type(self).runner
        type(self).last = self

    runner = None

    def get_bin_path(self, name, required=False):
        return {"koha-list": "/usr/sbin/koha-list", "koha-indexer": "/usr/sbin/koha-indexer",
                "koha-zebra": "/usr/sbin/koha-zebra", "koha-shell": "/usr/sbin/koha-shell",
                "systemctl": "/usr/bin/systemctl"}.get(name)

    def run_command(self, argv, **kwargs):
        self.commands.append(argv)
        return self.runner(argv)

    def exit_json(self, **kwargs):
        raise ModuleExit(kwargs)

    def fail_json(self, **kwargs):
        raise ModuleExit(kwargs)


def load_module():
    ansible = types.ModuleType("ansible")
    ansible_utils = types.ModuleType("ansible.module_utils")
    basic = types.ModuleType("ansible.module_utils.basic")
    basic.AnsibleModule = FakeAnsibleModule
    spec = importlib.util.spec_from_file_location("zebra_indexer_test", os.path.join(ROOT, "plugins/modules/zebra_indexer.py"))
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"ansible": ansible, "ansible.module_utils": ansible_utils,
                                      "ansible.module_utils.basic": basic}):
        spec.loader.exec_module(module)
    return module


class ZebraIndexerTest(unittest.TestCase):
    def setUp(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "started"}
        FakeAnsibleModule.check_mode = False
        self.module = load_module()
        patches = [
            mock.patch.object(self.module.os.path, "isdir", side_effect=lambda p: p in
                              ("/etc/koha/sites/biblioteca", "/run/systemd/system")),
            mock.patch.object(self.module.os.path, "isfile", return_value=True),
            mock.patch.object(self.module.os, "access", return_value=True),
            mock.patch.object(self.module.os, "geteuid", return_value=0),
            mock.patch.object(self.module.time, "sleep"),
            mock.patch.object(self.module.time, "monotonic", side_effect=[0, 1, 2, 3, 4, 6] * 20),
            mock.patch("builtins.open", mock.mock_open(read_data="")),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_module(self, runtime="active", enabled="enabled", zebra="active", engine="Zebra", action_effect=True):
        states = {"runtime": runtime, "enabled": enabled, "zebra": zebra}

        def runner(argv):
            joined = " ".join(argv)
            if argv[0].endswith("koha-list"):
                return 0, "biblioteca\n", ""
            if argv[0].endswith("koha-indexer") and "--help" in argv:
                return 0, "--start --stop --restart --status --enable --disable --quiet --help", ""
            if argv[0].endswith("koha-indexer") and len(argv) > 1 and argv[1].startswith("--"):
                operation = argv[1]
                if action_effect:
                    if operation in ("--start", "--restart"): states["runtime"] = "active"
                    if operation == "--stop": states["runtime"] = "inactive"
                    if operation == "--enable": states["enabled"] = "enabled"
                    if operation == "--disable": states["enabled"] = "disabled"
                return 0, "ok", ""
            if argv[0].endswith("koha-shell"):
                return 0, engine + "\n", ""
            if argv[0].endswith("koha-zebra"):
                return (0, "Zebra running for instance biblioteca", "") if states["zebra"] == "active" else (3, "Zebra not running for instance biblioteca", "")
            if "LoadState" in joined: return 0, "loaded\n", ""
            if "ActiveState" in joined:
                return 0, states["zebra" if "koha-zebra@" in joined else "runtime"] + "\n", ""
            if argv[1] == "is-enabled":
                value = states["enabled"]
                return (0 if value == "enabled" else 1), value + "\n", ""
            return 0, "", ""
        FakeAnsibleModule.runner = runner
        with self.assertRaises(ModuleExit) as raised:
            self.module.main()
        return raised.exception.result, FakeAnsibleModule.last.commands

    def test_start_stop_idempotence_and_explicit_restart(self):
        result, commands = self.run_module(runtime="inactive")
        self.assertEqual(result["actions"], ["start"])
        self.assertTrue(result["changed"])
        result, commands = self.run_module(runtime="active")
        self.assertFalse(result["changed"])
        self.assertFalse(any("--start" in command for command in commands))
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "stopped"}
        result, _ = self.run_module(runtime="active")
        self.assertEqual(result["actions"], ["stop"])
        result, _ = self.run_module(runtime="inactive")
        self.assertFalse(result["changed"])
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "restarted"}
        result, _ = self.run_module(runtime="inactive")
        self.assertEqual(result["actions"], ["restart"])
        self.assertTrue(result["changed"])

    def test_status_is_read_only_and_arguments_are_validated(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "status"}
        result, commands = self.run_module()
        self.assertFalse(result["changed"])
        self.assertFalse(any(arg in ("--start", "--stop", "--restart", "--enable", "--disable")
                             for command in commands for arg in command))
        FakeAnsibleModule.params = {"instance": "../bad", "state": "started"}
        result, commands = self.run_module()
        self.assertIn("instance must", result["msg"])
        self.assertEqual(commands, [])
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "status", "enabled": False}
        result, commands = self.run_module()
        self.assertIn("read-only", result["msg"])
        self.assertEqual(commands, [])

    def test_enable_disable_idempotence_combined_order_and_check_mode(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "enabled": True}
        result, _ = self.run_module(enabled="disabled")
        self.assertEqual(result["actions"], ["enable"])
        FakeAnsibleModule.params = {"instance": "biblioteca", "enabled": True}
        result, _ = self.run_module(enabled="enabled")
        self.assertFalse(result["changed"])
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "started", "enabled": False}
        FakeAnsibleModule.check_mode = True
        result, commands = self.run_module(runtime="inactive", enabled="enabled")
        self.assertEqual(result["planned_actions"], ["start", "disable"])
        self.assertEqual(result["state"], "stopped")
        self.assertEqual(result["enabled"], True)
        self.assertFalse(any("--start" in command or "--disable" in command for command in commands))
        FakeAnsibleModule.check_mode = False
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "started", "enabled": True}
        result, commands = self.run_module(runtime="inactive", enabled="disabled")
        operations = [command[1] for command in commands if command[0].endswith("koha-indexer") and
                      len(command) > 1 and command[1] in ("--enable", "--start", "--stop", "--disable")]
        self.assertEqual(operations, ["--enable", "--start"])
        self.assertEqual(result["actions"], ["enable", "start"])
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "stopped", "enabled": False}
        result, commands = self.run_module(runtime="active", enabled="enabled")
        operations = [command[1] for command in commands if command[0].endswith("koha-indexer") and
                      len(command) > 1 and command[1] in ("--enable", "--start", "--stop", "--disable")]
        self.assertEqual(operations, ["--stop", "--disable"])

    def test_sysv_enablement_is_rejected_and_status_is_inspected(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "enabled": True}
        FakeAnsibleModule.runner = lambda argv: (0, "biblioteca\n", "")
        with mock.patch.object(FakeAnsibleModule, "get_bin_path", autospec=True,
                               side_effect=lambda obj, name, required=False: None if name == "systemctl" else
                               {"koha-list": "/usr/sbin/koha-list", "koha-indexer": "/usr/sbin/koha-indexer"}.get(name)), \
             mock.patch.object(self.module.os.path, "isdir", side_effect=lambda p: p == "/etc/koha/sites/biblioteca"):
            with self.assertRaises(ModuleExit) as raised:
                self.module.main()
        self.assertIn("unsupported", raised.exception.result["msg"])

    def test_engine_zebra_dependency_alternate_exit_and_failed_postcondition(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "started", "verify_zebra_engine": True}
        result, _ = self.run_module(runtime="inactive", engine="Elasticsearch")
        self.assertIn("SearchEngine is Elasticsearch", result["msg"])
        self.assertEqual(result["search_engine"], "Elasticsearch")
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "started", "require_zebra_running": True}
        result, commands = self.run_module(runtime="inactive", zebra="inactive")
        self.assertIn("start it with jmz.koha.zebra", result["msg"])
        self.assertFalse(any("--start" in command for command in commands))
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "started"}
        result, _ = self.run_module(runtime="inactive", action_effect=False)
        self.assertIn("did not reach started", result["msg"])

    def test_command_nonzero_and_engine_query_failure_are_controlled(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "started", "verify_zebra_engine": True}
        def bad_engine(argv):
            if argv[0].endswith("koha-list"): return 0, "biblioteca\n", ""
            if "LoadState" in " ".join(argv): return 0, "loaded\n", ""
            if "ActiveState" in " ".join(argv): return 0, "inactive\n", ""
            if argv[0].endswith("koha-shell"): return 1, "", "database unavailable"
            return 0, "", ""
        FakeAnsibleModule.runner = bad_engine
        with self.assertRaises(ModuleExit) as raised:
            self.module.main()
        self.assertIn("Unable to reliably read SearchEngine", raised.exception.result["msg"])

    def test_alternate_indexer_static_override_blocks_mutations(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "started"}
        with mock.patch("builtins.open", mock.mock_open(read_data='ALTERNATE_INDEXER_DAEMON="/usr/local/bin/other-indexer"\n')):
            result, commands = self.run_module(runtime="inactive")
        self.assertIn("ALTERNATE_INDEXER_DAEMON selects", result["msg"])
        self.assertFalse(any("--start" in command for command in commands))

    def test_masked_and_missing_unit_states_are_not_guessed(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "status"}
        result, _ = self.run_module(runtime="inactive", enabled="masked")
        self.assertIsNone(result["enabled"])
        self.assertEqual(result["enablement_state"], "masked")
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "started"}
        result, _ = self.run_module(runtime="inactive", enabled="masked")
        self.assertIn("masked indexer unit", result["msg"])

    def test_transitional_runtime_is_reported_as_unknown_without_invention(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "status"}
        result, _ = self.run_module(runtime="activating")
        self.assertEqual(result["state"], "unknown")
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "stopped"}
        result, _ = self.run_module(runtime="deactivating")
        self.assertIn("transitional/unknown", result["msg"])

    def test_instance_binary_permission_and_enablement_option_failures(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "started"}
        with mock.patch.object(self.module.os.path, "isfile", return_value=False):
            result, _ = self.run_module()
        self.assertIn("does not exist", result["msg"])
        with mock.patch.object(FakeAnsibleModule, "get_bin_path", autospec=True,
                               side_effect=lambda obj, name, required=False: None if name == "koha-indexer" else
                               {"koha-list": "/usr/sbin/koha-list", "systemctl": "/usr/bin/systemctl"}.get(name)):
            result, _ = self.run_module()
        self.assertIn("koha-indexer was not found", result["msg"])
        with mock.patch.object(self.module.os, "geteuid", return_value=1000):
            result, _ = self.run_module()
        self.assertIn("become: true", result["msg"])

        FakeAnsibleModule.params = {"instance": "biblioteca", "enabled": True}
        def no_enable_help(argv):
            if argv[0].endswith("koha-list"): return 0, "biblioteca\n", ""
            if argv[0].endswith("koha-indexer") and "--help" in argv: return 0, "--start --stop --status", ""
            return 0, "loaded\n", ""
        FakeAnsibleModule.runner = no_enable_help
        with self.assertRaises(ModuleExit) as raised:
            self.module.main()
        self.assertIn("does not advertise --enable", raised.exception.result["msg"])

    def test_sysv_status_uses_koha_status_interface(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "status"}
        FakeAnsibleModule.runner = lambda argv: (0, "biblioteca\n", "") if argv[0].endswith("koha-list") else (
            0, "Indexer running for instance biblioteca", "")
        with mock.patch.object(FakeAnsibleModule, "get_bin_path", autospec=True,
                               side_effect=lambda obj, name, required=False: None if name == "systemctl" else
                               {"koha-list": "/usr/sbin/koha-list", "koha-indexer": "/usr/sbin/koha-indexer"}.get(name)), \
             mock.patch.object(self.module.os.path, "isdir", side_effect=lambda p: p == "/etc/koha/sites/biblioteca"):
            with self.assertRaises(ModuleExit) as raised:
                self.module.main()
        self.assertEqual(raised.exception.result["backend"], "sysv")
        self.assertEqual(raised.exception.result["state"], "started")
        self.assertTrue(any(command[0].endswith("koha-indexer") and "--status" in command
                            for command in FakeAnsibleModule.last.commands))


if __name__ == "__main__":
    unittest.main()
