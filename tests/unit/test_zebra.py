# SPDX-License-Identifier: MIT-0
"""Unit tests for the Zebra module with mocked Koha and service commands."""

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
    responses = []
    last = None

    def __init__(self, **kwargs):
        self.params = {"command_path": "/usr/sbin/koha-zebra", "verbose": False, **type(self).params}
        self.check_mode = type(self).check_mode
        self.commands = []
        self._responses = list(type(self).responses)
        type(self).last = self

    def get_bin_path(self, name, required=False):
        return {"koha-list": "/usr/sbin/koha-list", "koha-zebra": "/usr/sbin/koha-zebra",
                "systemctl": "/usr/bin/systemctl"}.get(name)

    def run_command(self, argv, **kwargs):
        self.commands.append(argv)
        if self._responses:
            return self._responses.pop(0)
        if argv[0].endswith("koha-list"):
            return 0, "biblioteca\narchivo\n", ""
        if "LoadState" in " ".join(argv):
            return 0, "loaded\n", ""
        if "ActiveState" in " ".join(argv):
            return 0, "active\n", ""
        if argv[1] == "is-enabled":
            return 0, "enabled\n", ""
        return 0, "", ""

    def exit_json(self, **kwargs):
        raise ModuleExit(kwargs)

    def fail_json(self, **kwargs):
        raise ModuleExit(kwargs)


def load_module():
    ansible = types.ModuleType("ansible")
    ansible_utils = types.ModuleType("ansible.module_utils")
    basic = types.ModuleType("ansible.module_utils.basic")
    basic.AnsibleModule = FakeAnsibleModule
    spec = importlib.util.spec_from_file_location("zebra_module_test", os.path.join(ROOT, "plugins/modules/zebra.py"))
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"ansible": ansible, "ansible.module_utils": ansible_utils,
                                      "ansible.module_utils.basic": basic}):
        spec.loader.exec_module(module)
    return module


class ZebraModuleTest(unittest.TestCase):
    def setUp(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "started"}
        FakeAnsibleModule.check_mode = False
        FakeAnsibleModule.responses = []
        self.module = load_module()
        self.patches = [
            mock.patch.object(self.module.os.path, "isdir", return_value=True),
            mock.patch.object(self.module.os.path, "isfile", return_value=True),
            mock.patch.object(self.module.os, "access", return_value=True),
            mock.patch.object(self.module.os, "geteuid", return_value=0),
            mock.patch.object(self.module.os.path, "isdir", side_effect=lambda p: p in ("/etc/koha/sites/biblioteca", "/run/systemd/system")),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_module(self):
        with self.assertRaises(ModuleExit) as raised:
            self.module.main()
        return raised.exception.result, FakeAnsibleModule.last.commands

    @staticmethod
    def sysd(runtime="active", enabled="enabled"):
        runtime_state = [runtime]
        enabled_state = [enabled]
        def response(argv):
            joined = " ".join(argv)
            if argv[0].endswith("koha-list"):
                return 0, "biblioteca\n", ""
            if argv[0].endswith("koha-zebra"):
                operation = argv[1]
                if operation == "--start" or operation == "--restart": runtime_state[0] = "active"
                if operation == "--stop": runtime_state[0] = "inactive"
                if operation == "--enable": enabled_state[0] = "enabled"
                if operation == "--disable": enabled_state[0] = "disabled"
                return 0, "ok\n", ""
            if "LoadState" in joined:
                return 0, "loaded\n", ""
            if "ActiveState" in joined:
                return 0, runtime_state[0] + "\n", ""
            if argv[1] == "is-enabled":
                value = enabled_state[0]
                return (0 if value == "enabled" else 1), value + "\n", ""
            return 0, "ok\n", ""
        return response

    def systemd_mock(self, runtime="active", enabled="enabled"):
        response = self.sysd(runtime, enabled)
        return lambda obj, argv, **kw: response(argv)

    def test_start_from_stopped_and_idempotent_start(self):
        calls = []
        def response(argv):
            calls.append(argv)
            if argv[0].endswith("koha-list"): return 0, "biblioteca\n", ""
            if "LoadState" in " ".join(argv): return 0, "loaded\n", ""
            if "ActiveState" in " ".join(argv): return 0, ("inactive" if len(calls) < 4 else "active") + "\n", ""
            if argv[1] == "is-enabled": return 1, "disabled\n", ""
            return 0, "", ""
        FakeAnsibleModule.responses = []
        FakeAnsibleModule.last = None
        with mock.patch.object(FakeAnsibleModule, "run_command", autospec=True, side_effect=lambda obj, argv, **kw: response(argv)):
            result, commands = self.run_module()
        self.assertTrue(result["changed"])
        self.assertEqual(result["actions"], ["start"])
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "started"}
        with mock.patch.object(FakeAnsibleModule, "run_command", autospec=True, side_effect=self.systemd_mock("active", "disabled")):
            result, commands = self.run_module()
        self.assertFalse(result["changed"])
        self.assertFalse(any("--start" in c for c in commands))

    def test_stop_active_and_already_stopped(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "stopped"}
        with mock.patch.object(FakeAnsibleModule, "run_command", autospec=True, side_effect=self.systemd_mock("active", "disabled")):
            result, commands = self.run_module()
        self.assertEqual(result["actions"], ["stop"])
        self.assertTrue(result["changed"])
        with mock.patch.object(FakeAnsibleModule, "run_command", autospec=True, side_effect=self.systemd_mock("inactive", "disabled")):
            result, commands = self.run_module()
        self.assertFalse(result["changed"])

    def test_restart_is_explicit_and_status_read_only(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "restarted"}
        with mock.patch.object(FakeAnsibleModule, "run_command", autospec=True, side_effect=self.systemd_mock()):
            result, commands = self.run_module()
        self.assertEqual(result["actions"], ["restart"])
        self.assertTrue(result["changed"])
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "status"}
        with mock.patch.object(FakeAnsibleModule, "run_command", autospec=True, side_effect=self.systemd_mock()):
            result, commands = self.run_module()
        self.assertFalse(result["changed"])
        self.assertFalse(any(len(c) > 1 and c[1].startswith("--") for c in commands))

    def test_systemd_enable_disable_idempotence_and_combined_order(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "enabled": True}
        with mock.patch.object(FakeAnsibleModule, "run_command", autospec=True, side_effect=self.systemd_mock("active", "disabled")):
            result, commands = self.run_module()
        self.assertEqual(result["actions"], ["enable"])
        FakeAnsibleModule.params = {"instance": "biblioteca", "enabled": True}
        with mock.patch.object(FakeAnsibleModule, "run_command", autospec=True, side_effect=self.systemd_mock()):
            result, _ = self.run_module()
        self.assertFalse(result["changed"])
        FakeAnsibleModule.params = {"instance": "biblioteca", "enabled": False}
        with mock.patch.object(FakeAnsibleModule, "run_command", autospec=True, side_effect=self.systemd_mock("active", "enabled")):
            result, _ = self.run_module()
        self.assertEqual(result["actions"], ["disable"])
        FakeAnsibleModule.params = {"instance": "biblioteca", "enabled": True, "state": "started"}
        with mock.patch.object(FakeAnsibleModule, "run_command", autospec=True, side_effect=self.systemd_mock("inactive", "disabled")):
            result, _ = self.run_module()
        self.assertEqual(result["actions"], ["enable", "start"])
        FakeAnsibleModule.params = {"instance": "biblioteca", "enabled": False, "state": "stopped"}
        with mock.patch.object(FakeAnsibleModule, "run_command", autospec=True, side_effect=self.systemd_mock("active", "enabled")):
            result, _ = self.run_module()
        self.assertEqual(result["actions"], ["stop", "disable"])

    def test_sysv_enablement_is_unsupported_and_state_is_observed(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "status"}
        responses = iter([(0, "biblioteca\n", ""), (0, "not-found\n", ""), (3, "Zebra not running for biblioteca", "")])
        with mock.patch.object(FakeAnsibleModule, "get_bin_path", autospec=True,
                               side_effect=lambda obj, name, required=False: None if name == "systemctl" else "/usr/sbin/" + name), \
             mock.patch.object(FakeAnsibleModule, "run_command", autospec=True, side_effect=lambda obj, argv, **kw: next(responses)), \
             mock.patch.object(self.module.os.path, "isdir", side_effect=lambda p: p == "/etc/koha/sites/biblioteca"):
            result, _ = self.run_module()
        self.assertEqual(result["backend"], "sysv")
        self.assertIsNone(result["enabled"])
        FakeAnsibleModule.params = {"instance": "biblioteca", "enabled": True}
        with mock.patch.object(FakeAnsibleModule, "get_bin_path", autospec=True,
                               side_effect=lambda obj, name, required=False: None if name == "systemctl" else "/usr/sbin/" + name), \
             mock.patch.object(FakeAnsibleModule, "run_command", autospec=True, side_effect=lambda obj, argv, **kw: (0, "biblioteca\n", "")), \
             mock.patch.object(self.module.os.path, "isdir", side_effect=lambda p: p == "/etc/koha/sites/biblioteca"):
            result, _ = self.run_module()
        self.assertIn("unsupported", result["msg"])

    def test_invalid_missing_instance_binary_and_privilege_failures(self):
        FakeAnsibleModule.params = {"instance": "../bad", "state": "started"}
        result, commands = self.run_module()
        self.assertIn("instance must", result["msg"])
        self.assertEqual(commands, [])
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "started"}
        with mock.patch.object(self.module.os.path, "isdir", return_value=False):
            result, _ = self.run_module()
        self.assertIn("does not exist", result["msg"])
        with mock.patch.object(FakeAnsibleModule, "get_bin_path", return_value=None):
            result, _ = self.run_module()
        self.assertIn("koha-list", result["msg"])
        def binary_lookup(obj, name, required=False):
            return None if name == "koha-zebra" else "/usr/sbin/koha-list" if name == "koha-list" else "/usr/bin/systemctl"
        with mock.patch.object(FakeAnsibleModule, "get_bin_path", autospec=True, side_effect=binary_lookup):
            result, _ = self.run_module()
        self.assertIn("koha-zebra was not found", result["msg"])
        with mock.patch.object(self.module.os, "geteuid", return_value=1000):
            result, _ = self.run_module()
        self.assertIn("become: true", result["msg"])

    def test_command_success_without_state_change_and_operation_error(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "started"}
        def remains_stopped(argv):
            if argv[0].endswith("koha-list"): return 0, "biblioteca\n", ""
            if "LoadState" in " ".join(argv): return 0, "loaded\n", ""
            if "ActiveState" in " ".join(argv): return 0, "inactive\n", ""
            if argv[1] == "is-enabled": return 1, "disabled\n", ""
            return 0, "did nothing\n", ""
        with mock.patch.object(FakeAnsibleModule, "run_command", autospec=True, side_effect=lambda obj, argv, **kw: remains_stopped(argv)):
            result, _ = self.run_module()
        self.assertIn("did not reach started", result["msg"])
        def fails(argv):
            if argv[0].endswith("koha-list"): return 0, "biblioteca\n", ""
            if "LoadState" in " ".join(argv): return 0, "loaded\n", ""
            if "ActiveState" in " ".join(argv): return 0, "inactive\n", ""
            if argv[1] == "is-enabled": return 1, "disabled\n", ""
            return 1, "", "Permission denied"
        with mock.patch.object(FakeAnsibleModule, "run_command", autospec=True, side_effect=lambda obj, argv, **kw: fails(argv)):
            result, _ = self.run_module()
        self.assertIn("failed", result["msg"])
        self.assertIn("Permission denied", result["msg"])
        self.assertTrue(result["changed"] is False)

        enabled_state = ["disabled"]
        def partial_combined(argv):
            if argv[0].endswith("koha-list"): return 0, "biblioteca\n", ""
            if "LoadState" in " ".join(argv): return 0, "loaded\n", ""
            if "ActiveState" in " ".join(argv): return 0, "inactive\n", ""
            if argv[1] == "is-enabled": return (0 if enabled_state[0] == "enabled" else 1), enabled_state[0] + "\n", ""
            if argv[0].endswith("koha-zebra") and argv[1] == "--enable":
                enabled_state[0] = "enabled"
                return 0, "enabled\n", ""
            return 1, "", "Permission denied"
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "started", "enabled": True}
        with mock.patch.object(FakeAnsibleModule, "run_command", autospec=True,
                               side_effect=lambda obj, argv, **kw: partial_combined(argv)):
            result, _ = self.run_module()
        self.assertTrue(result["changed"])
        self.assertEqual(result["actions"], ["enable", "start"])
        self.assertEqual(result["actions_status"], "attempted")

    def test_check_mode_plans_only_and_structured_results(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "started", "enabled": True}
        FakeAnsibleModule.check_mode = True
        with mock.patch.object(FakeAnsibleModule, "run_command", autospec=True, side_effect=self.systemd_mock("inactive", "disabled")):
            result, commands = self.run_module()
        self.assertTrue(result["changed"])
        self.assertEqual(result["actions"], ["enable", "start"])
        self.assertEqual(result["actions_status"], "planned")
        self.assertEqual(result["state"], "started")
        self.assertEqual(result["enabled"], True)
        self.assertFalse(any(c[0].endswith("koha-zebra") and "--" in " ".join(c) for c in commands))
        self.assertIn("previous_state", result)
        self.assertIn("previous_enabled", result)
        self.assertIn("diagnostics", result)
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "restarted"}
        with mock.patch.object(FakeAnsibleModule, "run_command", autospec=True, side_effect=self.systemd_mock()):
            result, commands = self.run_module()
        self.assertTrue(result["changed"])
        self.assertEqual(result["actions"], ["restart"])
        self.assertEqual(result["actions_status"], "planned")
        self.assertFalse(any(c[0].endswith("koha-zebra") for c in commands))

    def test_masked_static_and_missing_systemd_units_are_not_booleans(self):
        for unit_state in ("masked", "static", "not-found"):
            FakeAnsibleModule.params = {"instance": "biblioteca", "state": "status"}
            with mock.patch.object(FakeAnsibleModule, "run_command", autospec=True,
                                   side_effect=self.systemd_mock("active", unit_state)):
                result, _ = self.run_module()
            self.assertIsNone(result["enabled"])
            self.assertEqual(result["enablement_state"], unit_state)


if __name__ == "__main__":
    unittest.main()
