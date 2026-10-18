# SPDX-License-Identifier: MIT-0
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
        self.params = dict(type(self).params)
        self.check_mode = type(self).check_mode
        self.commands = []
        self._responses = list(type(self).responses)
        type(self).last = self

    def get_bin_path(self, name, required=False):
        return "/usr/sbin/koha-plack"

    def run_command(self, argv, **kwargs):
        self.commands.append(argv)
        if self._responses:
            return self._responses.pop(0)
        return (0, "Plack running for biblioteca:.", "")

    def exit_json(self, **kwargs):
        raise ModuleExit(kwargs)

    def fail_json(self, **kwargs):
        raise ModuleExit(kwargs)


def load_module():
    ansible = types.ModuleType("ansible")
    ansible_utils = types.ModuleType("ansible.module_utils")
    basic = types.ModuleType("ansible.module_utils.basic")
    basic.AnsibleModule = FakeAnsibleModule
    spec = importlib.util.spec_from_file_location("plack_module_test", os.path.join(ROOT, "plugins/modules/plack.py"))
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"ansible": ansible, "ansible.module_utils": ansible_utils,
                                      "ansible.module_utils.basic": basic}):
        spec.loader.exec_module(module)
    return module


class PlackModuleTest(unittest.TestCase):
    def setUp(self):
        FakeAnsibleModule.params = {"instance": "biblioteca"}
        FakeAnsibleModule.check_mode = False
        FakeAnsibleModule.responses = [(0, "Plack running for biblioteca:.", "")]
        self.module = load_module()
        self.config = "/etc/apache2/sites-available/biblioteca.conf"
        self.config_content = "Include /etc/koha/apache-shared-opac-plack.conf\nInclude /etc/koha/apache-shared-intranet-plack.conf\n"
        self._patches = [
            mock.patch.object(self.module.os.path, "isfile", side_effect=lambda p: p in (
                "/etc/koha/sites/biblioteca/koha-conf.xml", self.config)),
            mock.patch("builtins.open", mock.mock_open(read_data=self.config_content)),
        ]
        for patcher in self._patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _run(self):
        with self.assertRaises(ModuleExit) as raised:
            self.module.main()
        return raised.exception.result, FakeAnsibleModule.last.commands

    def test_start_stopped_and_start_running(self):
        FakeAnsibleModule.params["state"] = "started"
        FakeAnsibleModule.responses = [(3, "Plack not running for biblioteca", ""), (0, "started", ""),
                                       (0, "Plack running for biblioteca", "")]
        result, commands = self._run()
        self.assertTrue(result["changed"])
        self.assertEqual(commands[1], ["/usr/sbin/koha-plack", "--start", "biblioteca"])
        FakeAnsibleModule.responses = [(0, "Plack running for biblioteca", "")]
        result, commands = self._run()
        self.assertFalse(result["changed"])
        self.assertEqual(len(commands), 1)  # status only

    def test_stop_active_and_already_stopped(self):
        FakeAnsibleModule.params["state"] = "stopped"
        FakeAnsibleModule.responses = [(0, "Plack running for biblioteca", ""), (0, "stopped", ""),
                                       (3, "Plack not running for biblioteca", "")]
        result, commands = self._run()
        self.assertEqual(commands[1][1], "--stop")
        self.assertTrue(result["changed"])
        FakeAnsibleModule.responses = [(3, "Plack not running for biblioteca", "")]
        result, commands = self._run()
        self.assertFalse(result["changed"])
        self.assertEqual(len(commands), 1)

    def test_restart_and_reload_are_explicit_changes(self):
        for state, operation in (("restarted", "--restart"), ("reloaded", "--reload")):
            FakeAnsibleModule.params["state"] = state
            FakeAnsibleModule.responses = [(0, "Plack running for biblioteca", ""), (0, "done", ""),
                                           (0, "Plack running for biblioteca", "")]
            result, commands = self._run()
            self.assertTrue(result["changed"])
            self.assertEqual(commands[1][1], operation)

    def test_enable_disable_and_combinations(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "enabled": False}
        FakeAnsibleModule.responses = [(0, "Plack running for biblioteca", ""), (0, "disabled", "")]
        active = mock.mock_open(read_data="Include /etc/koha/apache-shared-opac-plack.conf\nInclude /etc/koha/apache-shared-intranet-plack.conf\n").return_value
        disabled = mock.mock_open(read_data="#Include /etc/koha/apache-shared-opac-plack.conf\n#Include /etc/koha/apache-shared-intranet-plack.conf\n").return_value
        with mock.patch("builtins.open", side_effect=[active, disabled]):
            result, commands = self._run()
        self.assertTrue(result["changed"])
        self.assertEqual(commands[-1][1], "--disable")
        FakeAnsibleModule.params = {"instance": "biblioteca", "enabled": True, "state": "started"}
        FakeAnsibleModule.responses = [(3, "Plack not running for biblioteca", ""), (0, "enabled", ""),
                                       (0, "started", ""), (0, "Plack running for biblioteca", "")]
        disabled = mock.mock_open(read_data="#Include /etc/koha/apache-shared-opac-plack.conf\n#Include /etc/koha/apache-shared-intranet-plack.conf\n").return_value
        enabled = mock.mock_open(read_data="Include /etc/koha/apache-shared-opac-plack.conf\nInclude /etc/koha/apache-shared-intranet-plack.conf\n").return_value
        with mock.patch("builtins.open", side_effect=[disabled, enabled]):
            result, commands = self._run()
        self.assertEqual([x[1] for x in commands[1:-1]], ["--enable", "--start"])
        self.assertEqual(result["actions"], ["enable", "start"])

    def test_query_and_check_mode(self):
        result, commands = self._run()
        self.assertFalse(result["changed"])
        self.assertEqual(commands, [["/usr/sbin/koha-plack", "--status", "biblioteca"]])
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "started", "enabled": False}
        FakeAnsibleModule.check_mode = True
        FakeAnsibleModule.responses = [(3, "Plack not running for biblioteca", "")]
        result, commands = self._run()
        self.assertTrue(result["changed"])
        self.assertEqual(result["actions"], ["disable", "start"])
        self.assertEqual(len(commands), 1)

    def test_repeated_enablement_is_idempotent(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "enabled": True}
        FakeAnsibleModule.responses = [(0, "Plack running for biblioteca", "")]
        result, commands = self._run()
        self.assertFalse(result["changed"])
        self.assertEqual(commands, [["/usr/sbin/koha-plack", "--status", "biblioteca"]])

    def test_missing_instance_binary_invalid_status_and_permission_error(self):
        with mock.patch.object(self.module.os.path, "isfile", return_value=False):
            result, _ = self._run()
            self.assertIn("does not exist", result["msg"])
        FakeAnsibleModule.params = {"instance": "biblioteca"}
        with mock.patch.object(FakeAnsibleModule, "get_bin_path", return_value=None):
            result, _ = self._run()
            self.assertIn("not found", result["msg"])
        FakeAnsibleModule.responses = [(1, "", "Permission denied")]
        result, _ = self._run()
        self.assertIn("Unable to determine", result["msg"])
        FakeAnsibleModule.responses = [(0, "nonsense", "")]
        result, _ = self._run()
        self.assertIn("did not identify", result["msg"])
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "started"}
        FakeAnsibleModule.responses = [(3, "Plack not running for biblioteca", ""), (1, "", "Permission denied")]
        result, _ = self._run()
        self.assertIn("--start failed", result["msg"])

    def test_inconsistent_enable_state_fails_and_status_is_read_only(self):
        self.config_content = "Include /etc/koha/apache-shared-opac-plack.conf\n"
        with mock.patch("builtins.open", mock.mock_open(read_data=self.config_content)):
            result, _ = self._run()
        self.assertIn("inconsistent", result["msg"])
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "status", "enabled": True}
        result, commands = self._run()
        self.assertIn("read-only", result["msg"])
        self.assertEqual(commands, [])


if __name__ == "__main__":
    unittest.main()
