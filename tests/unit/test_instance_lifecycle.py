# SPDX-License-Identifier: MIT-0
import importlib.util
import io
import json
import os
import sys
import types
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
HELPER_SPEC = importlib.util.spec_from_file_location("koha_instance", os.path.join(ROOT, "plugins/module_utils/koha_instance.py"))
helper = importlib.util.module_from_spec(HELPER_SPEC)
HELPER_SPEC.loader.exec_module(helper)


class ModuleExit(Exception):
    def __init__(self, result):
        self.result = result


class FakeAnsibleModule:
    params = {}
    check_mode = False
    last = None

    def __init__(self, **kwargs):
        self.params = dict(type(self).params)
        self.check_mode = type(self).check_mode
        self.commands = []
        type(self).last = self

    def run_command(self, argv, **kwargs):
        self.commands.append((argv, kwargs))
        return (0, "", "")

    def exit_json(self, **kwargs):
        raise ModuleExit(kwargs)

    def fail_json(self, **kwargs):
        raise ModuleExit(kwargs)


def load_module():
    ansible = types.ModuleType("ansible")
    ansible_utils = types.ModuleType("ansible.module_utils")
    ansible_basic = types.ModuleType("ansible.module_utils.basic")
    ansible_basic.AnsibleModule = FakeAnsibleModule
    collections = types.ModuleType("ansible_collections")
    jmz = types.ModuleType("ansible_collections.jmz")
    koha = types.ModuleType("ansible_collections.jmz.koha")
    plugins = types.ModuleType("ansible_collections.jmz.koha.plugins")
    module_utils = types.ModuleType("ansible_collections.jmz.koha.plugins.module_utils")
    module_utils.koha_instance = helper
    modules = {
        "ansible": ansible, "ansible.module_utils": ansible_utils,
        "ansible.module_utils.basic": ansible_basic,
        "ansible_collections": collections, "ansible_collections.jmz": jmz,
        "ansible_collections.jmz.koha": koha, "ansible_collections.jmz.koha.plugins": plugins,
        "ansible_collections.jmz.koha.plugins.module_utils": module_utils,
        "ansible_collections.jmz.koha.plugins.module_utils.koha_instance": helper,
    }
    spec = importlib.util.spec_from_file_location("instance_module_test", os.path.join(ROOT, "plugins/modules/instance.py"))
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


class InstanceLifecycleTest(unittest.TestCase):
    def setUp(self):
        FakeAnsibleModule.params = {"name": "biblioteca", "state": "absent", "db_mode": "create",
                                    "confirm_name": "biblioteca", "confirm_data_loss": True,
                                    "remove_database": False, "purge_data": False}
        FakeAnsibleModule.check_mode = False
        self.module = load_module()

    def test_apache_prerequisites_report_missing_apache_module_actionably(self):
        fake = types.SimpleNamespace(run_command=lambda argv, **kwargs: (0, " mpm_itk_module (shared)\n", ""))
        with mock.patch.object(self.module.os.path, "exists", return_value=True):
            with self.assertRaisesRegex(helper.ModuleInputError, "a2enmod rewrite"):
                self.module._check_apache_prerequisites(fake)

        fake.run_command = lambda argv, **kwargs: (0, " mpm_itk_module (shared)\n rewrite_module (shared)\n", "")
        with mock.patch.object(self.module.os.path, "exists", return_value=True):
            with self.assertRaisesRegex(helper.ModuleInputError, "a2enmod cgi"):
                self.module._check_apache_prerequisites(fake)

    def test_backend_failure_hint_never_echoes_database_diagnostics(self):
        output = "ERROR 1045: Access denied for user 'koha_test' using password: super-secret"
        self.assertEqual(
            self.module._safe_backend_failure_hint(output),
            "MariaDB rechazó la autenticación; revise su configuración local sin compartir credenciales.",
        )
        self.assertNotIn("super-secret", self.module._safe_backend_failure_hint(output))

    def _run_remove(self, check_mode=False):
        FakeAnsibleModule.check_mode = check_mode
        with mock.patch.object(self.module, "inspect_state", return_value=("present", {"config": True, "apache": True, "site_dir": True, "user": True, "group": True}, {})), \
             mock.patch.object(self.module.os, "geteuid", return_value=0), \
             mock.patch.object(self.module.os.path, "isdir", return_value=True), \
             mock.patch.object(self.module.os.path, "exists", return_value=False), \
             mock.patch.object(self.module.shutil, "which", return_value="/usr/sbin/koha-remove"):
            with self.assertRaises(ModuleExit) as raised:
                self.module.main()
        return raised.exception.result, FakeAnsibleModule.last.commands

    def test_absent_preserves_database_by_default(self):
        result, commands = self._run_remove()
        self.assertTrue(result["changed"])
        self.assertEqual(commands[0][0], ["/usr/sbin/koha-remove", "--keep-mysql", "biblioteca"])

    def test_absent_explicitly_purges_database_and_data(self):
        FakeAnsibleModule.params["remove_database"] = True
        FakeAnsibleModule.params["purge_data"] = True
        _, commands = self._run_remove()
        self.assertEqual(commands[0][0], ["/usr/sbin/koha-remove", "--purge-all", "biblioteca"])

    def test_absent_check_mode_does_not_call_backend(self):
        result, commands = self._run_remove(check_mode=True)
        self.assertTrue(result["changed"])
        self.assertEqual(commands, [])

    def test_absent_needs_both_confirmations(self):
        FakeAnsibleModule.params["confirm_name"] = "other"
        result, commands = self._run_remove()
        self.assertIn("confirm_name=name", result["msg"])
        self.assertEqual(commands, [])

    def test_reconfigure_check_mode_plans_database_preserving_rebuild(self):
        FakeAnsibleModule.params = {"name": "biblioteca", "state": "present", "db_mode": "create",
                                    "reconfigure": True, "confirm_name": "biblioteca", "confirm_data_loss": True}
        FakeAnsibleModule.check_mode = True
        fingerprint = self.module._safe_fingerprint(FakeAnsibleModule.params)
        saved = json.dumps({"state": "present", "fingerprint": "old-fingerprint"})
        with mock.patch.object(self.module, "inspect_state", return_value=("present", {}, {})), \
             mock.patch.object(self.module, "_find_binary", return_value="/usr/sbin/koha-create"), \
             mock.patch.object(self.module.os, "geteuid", return_value=0), \
             mock.patch.object(self.module.os.path, "isfile", return_value=False), \
             mock.patch("builtins.open", return_value=io.StringIO(saved)):
            with self.assertRaises(ModuleExit) as raised:
                self.module.main()
        self.assertTrue(raised.exception.result["changed"])
        self.assertEqual(raised.exception.result["actions"], ["koha-remove --keep-mysql", "koha-create --use-db"])
        self.assertNotEqual(fingerprint, "old-fingerprint")

    def test_partial_repair_check_mode_plans_rebuild(self):
        FakeAnsibleModule.params = {"name": "biblioteca", "state": "present", "db_mode": "create",
                                    "repair": True, "confirm_name": "biblioteca", "confirm_data_loss": True}
        FakeAnsibleModule.check_mode = True
        with mock.patch.object(self.module, "inspect_state", return_value=("partial", {"config": True}, {})), \
             mock.patch.object(self.module, "_find_binary", return_value="/usr/sbin/koha-create"), \
             mock.patch.object(self.module.os, "geteuid", return_value=0), \
             mock.patch.object(self.module.os.path, "isfile", return_value=False):
            with self.assertRaises(ModuleExit) as raised:
                self.module.main()
        self.assertTrue(raised.exception.result["changed"])
        self.assertEqual(raised.exception.result["actions"], ["koha-remove --keep-mysql", "koha-create --use-db"])

    def test_passwdfile_record_is_validated_without_echoing_secret(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as stream:
            stream.write("biblioteca:koha_biblioteca:Strong.Pass-1:koha_biblioteca:db.example.org\n")
            stream.flush()
            record = self.module._read_passwd_record(stream.name, "biblioteca")
            self.assertEqual(record[1], "koha_biblioteca")
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as stream:
            stream.write("biblioteca:koha_biblioteca:bad/secret:koha_biblioteca:localhost\n")
            stream.flush()
            with self.assertRaises(helper.ModuleInputError) as raised:
                self.module._read_passwd_record(stream.name, "biblioteca")
            self.assertNotIn("bad/secret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
