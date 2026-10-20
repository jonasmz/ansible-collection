# SPDX-License-Identifier: MIT-0
"""Unit tests for translate using a simulated koha-translate CLI."""

import importlib.util
import os
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


class ModuleExit(Exception):
    def __init__(self, result):
        self.result = result


class FakeAnsibleModule:
    params = {}
    check_mode = False
    diff = False
    runner = None
    last = None

    def __init__(self, **kwargs):
        defaults = {"name": "es-ES", "state": "present", "update": False,
                    "dev_instance": None, "verbose": False}
        defaults.update(type(self).params)
        self.params = defaults
        self.check_mode = type(self).check_mode
        self._diff = type(self).diff
        self.commands = []
        type(self).last = self

    def get_bin_path(self, name, required=False):
        return "/usr/sbin/koha-translate"

    def run_command(self, argv, **kwargs):
        self.commands.append(list(argv))
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
    path = os.path.join(ROOT, "plugins/modules/translate.py")
    spec = importlib.util.spec_from_file_location("translate_test", path)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"ansible": ansible, "ansible.module_utils": ansible_utils,
                                      "ansible.module_utils.basic": basic}):
        spec.loader.exec_module(module)
    return module


class TranslateTest(unittest.TestCase):
    def setUp(self):
        FakeAnsibleModule.params = {}
        FakeAnsibleModule.check_mode = False
        FakeAnsibleModule.diff = False
        self.module = load_module()
        for patcher in (
            mock.patch.object(self.module.os.path, "isfile", return_value=True),
            mock.patch.object(self.module.os, "access", return_value=True),
            mock.patch.object(self.module, "_development_tree", return_value="/tmp/koha-dev"),
            mock.patch.object(self.module, "_mutation_lock", self.noop_lock()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def noop_lock():
        from contextlib import contextmanager

        @contextmanager
        def lock(_path):
            yield
        return lock

    def run_module(self, installed=None, available=None, rc_by_op=None, stdout_override=None,
                   stderr_override=None):
        installed = set(installed or [])
        available = set(available if available is not None else ["es-ES", "es-AR", "fr-FR"])
        rc_by_op = rc_by_op or {}
        stdout_override = stdout_override or {}
        stderr_override = stderr_override or {}
        help_text = "--list --available --check --install --update --remove --dev --verbose --help"

        def runner(argv):
            operation = argv[1] if len(argv) > 1 else ""
            if operation == "--help":
                return 0, help_text, ""
            if operation == "--list":
                codes = installed if "--available" not in argv else available
                return 0, "".join(code + "\n" for code in sorted(codes)), ""
            if operation == "--check":
                return rc_by_op.get("--check", 0), stdout_override.get("--check", ""), stderr_override.get("--check", "")
            if operation == "--install":
                rc = rc_by_op.get("--install", 0)
                if rc == 0:
                    installed.add(argv[2])
                return rc, stdout_override.get("--install", ""), stderr_override.get("--install", "")
            if operation == "--update":
                rc = rc_by_op.get("--update", 0)
                if rc == 0:
                    installed.add(argv[2])
                else:
                    installed.discard(argv[2])
                return rc, stdout_override.get("--update", ""), stderr_override.get("--update", "")
            if operation == "--remove":
                rc = rc_by_op.get("--remove", 0)
                if rc == 0:
                    installed.discard(argv[2])
                return rc, stdout_override.get("--remove", ""), stderr_override.get("--remove", "")
            return 2, "", "unexpected command"

        FakeAnsibleModule.runner = runner
        with self.assertRaises(ModuleExit) as raised:
            self.module.main()
        return raised.exception.result, FakeAnsibleModule.last.commands

    def test_language_and_instance_validators(self):
        for code in ("es", "es-ES", "zh-Hans-CN", "en-GB"):
            self.assertEqual(self.module.validate_language(code), code)
        for code in ("", "../es", "es_ES", "--help", "a/b", "éS"):
            with self.assertRaises(self.module.TranslateError):
                self.module.validate_language(code)
        for instance in ("koha", "koha-dev", "a1"):
            self.assertEqual(self.module.validate_instance(instance), instance)
        for instance in ("", "Upper", "../x", "a" * 12, "with_underscore"):
            with self.assertRaises(self.module.TranslateError):
                self.module.validate_instance(instance)

    def test_development_instance_requires_git_configuration_and_checkout(self):
        self.module = load_module()
        root = ET.fromstring("<config><git_install>1</git_install><intranetdir>/srv/koha-dev</intranetdir></config>")
        parsed = types.SimpleNamespace(getroot=lambda: root)
        with mock.patch.object(self.module.os.path, "isfile", return_value=True), \
                mock.patch.object(self.module.ET, "parse", return_value=parsed), \
                mock.patch.object(self.module.os.path, "isdir", return_value=True):
            self.assertEqual(self.module._development_tree("koha-dev"), "/srv/koha-dev")
        production = ET.fromstring("<config><git_install>0</git_install><intranetdir>/srv/koha</intranetdir></config>")
        with mock.patch.object(self.module.os.path, "isfile", return_value=True), \
                mock.patch.object(self.module.ET, "parse", return_value=types.SimpleNamespace(getroot=lambda: production)):
            with self.assertRaisesRegex(self.module.TranslateError, "not configured as a development"):
                self.module._development_tree("koha-prod")

    def test_exact_list_parsing_and_empty_list(self):
        class Runner:
            def run_command(self, argv):
                return 0, "es-ES\nes-ES\nes-AR\n", ""
        codes, _ = self.module._query_languages(Runner(), "/usr/sbin/koha-translate", "installed", None)
        self.assertEqual(codes, ["es-ES", "es-AR"])
        class EmptyRunner:
            def run_command(self, argv):
                return 0, "", ""
        codes, _ = self.module._query_languages(EmptyRunner(), "/usr/sbin/koha-translate", "installed", None)
        self.assertEqual(codes, [])
        self.assertNotIn("es-ES", codes)
        class KohaEmptyListRunner:
            def run_command(self, argv):
                return 1, "", ""
        codes, result = self.module._query_languages(KohaEmptyListRunner(), "/usr/sbin/koha-translate", "installed", None)
        self.assertEqual(codes, [])
        self.assertEqual(result["rc"], 1)
        class BadRunner:
            def run_command(self, argv):
                return 0, "Installed languages:\n", ""
        with self.assertRaises(self.module.TranslateError):
            self.module._query_languages(BadRunner(), "/usr/sbin/koha-translate", "installed", None)

    def test_install_absent_then_second_run_is_idempotent(self):
        result, commands = self.run_module()
        self.assertTrue(result["changed"])
        self.assertEqual(result["action_executed"], "install")
        self.assertTrue(result["installed"])
        self.assertEqual(result["cmd"], ["/usr/sbin/koha-translate", "--install", "es-ES"])
        self.assertEqual(result["rc"], 0)
        self.assertIn(["/usr/sbin/koha-translate", "--install", "es-ES"], commands)
        result, commands = self.run_module(installed=["es-ES"])
        self.assertFalse(result["changed"])
        self.assertIsNone(result["action_executed"])
        self.assertFalse(any(c[1] in ("--install", "--update", "--remove") for c in commands))

    def test_absent_removal_and_second_absent_run(self):
        FakeAnsibleModule.params = {"name": "fr-FR", "state": "absent"}
        result, commands = self.run_module(installed=["fr-FR"], available=["fr-FR"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["action_executed"], "remove")
        FakeAnsibleModule.params = {"name": "fr-FR", "state": "absent"}
        result, commands = self.run_module(installed=[])
        self.assertFalse(result["changed"])

    def test_update_and_base_english(self):
        FakeAnsibleModule.params = {"name": "es-ES", "update": True}
        result, commands = self.run_module(installed=["es-ES"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["action_executed"], "update")
        self.assertIn(["/usr/sbin/koha-translate", "--update", "es-ES"], commands)
        FakeAnsibleModule.params = {"name": "en"}
        result, commands = self.run_module()
        self.assertFalse(result["changed"])
        self.assertTrue(result["installed"])
        self.assertFalse(any("--install" in c or "--list" in c for c in commands))
        FakeAnsibleModule.params = {"name": "en", "state": "absent"}
        result, _ = self.run_module()
        self.assertTrue(result["failed"])
        self.assertIn("cannot be removed", result["msg"])

    def test_update_requested_for_absent_language_installs(self):
        FakeAnsibleModule.params = {"name": "es-ES", "update": True}
        result, commands = self.run_module(installed=[])
        self.assertTrue(result["changed"])
        self.assertEqual(result["action_executed"], "install")
        self.assertIn(["/usr/sbin/koha-translate", "--install", "es-ES"], commands)

    def test_absent_and_installed_present_do_not_query_availability(self):
        FakeAnsibleModule.params = {"name": "es-ES", "state": "absent"}
        result, commands = self.run_module(installed=[])
        self.assertFalse(result["changed"])
        self.assertFalse(any("--available" in c for c in commands))
        FakeAnsibleModule.params = {"name": "es-ES", "state": "present"}
        result, commands = self.run_module(installed=["es-ES"])
        self.assertFalse(result["changed"])
        self.assertFalse(any("--available" in c for c in commands))

    def test_scopes_and_cli_argument_limit(self):
        FakeAnsibleModule.params = {"dev_instance": "koha-dev"}
        result, commands = self.run_module()
        self.assertTrue(result["changed"], result)
        self.assertEqual(result["scope"], "development")
        self.assertIn(["/usr/sbin/koha-translate", "--install", "es-ES", "--dev", "koha-dev"], commands)
        FakeAnsibleModule.params = {"dev_instance": "koha-dev", "verbose": True}
        result, commands = self.run_module()
        self.assertTrue(result["failed"])
        self.assertIn("four argv", result["msg"])
        self.assertEqual(commands, [])

    def test_unknown_unavailable_and_incomplete_po(self):
        result, _ = self.run_module(available=[])
        self.assertTrue(result["failed"])
        self.assertIn("not available", result["msg"])
        result, _ = self.run_module(rc_by_op={"--check": 1}, stderr_override={"--check": "Error: x-pref.po not found"})
        self.assertTrue(result["failed"])
        self.assertIn("PO files are incomplete", result["msg"])

    def test_check_mode_and_diff_mode(self):
        FakeAnsibleModule.check_mode = True
        FakeAnsibleModule.diff = True
        result, commands = self.run_module()
        self.assertTrue(result["changed"])
        self.assertEqual(result["planned_action"], "install")
        self.assertEqual(result["action_executed"], None)
        self.assertEqual(result["diff"]["before"]["installed"], False)
        self.assertEqual(result["diff"]["after"]["installed"], True)
        self.assertFalse(any(c[1] in ("--install", "--update", "--remove") for c in commands))
        FakeAnsibleModule.params = {"name": "es-ES"}
        result, _ = self.run_module(installed=["es-ES"])
        self.assertFalse(result["changed"])
        self.assertIsNone(result["planned_action"])

    def test_dev_scope_does_not_fallback_and_validation_precedes_cli(self):
        FakeAnsibleModule.params = {"dev_instance": "production"}
        with mock.patch.object(self.module, "_development_tree", side_effect=self.module.TranslateError("not development")):
            result, commands = self.run_module()
        self.assertTrue(result["failed"])
        self.assertEqual(commands, [])

    def test_operation_failure_has_changed_and_diagnostics(self):
        FakeAnsibleModule.params = {"name": "es-ES", "update": True}
        result, _ = self.run_module(installed=["es-ES"], rc_by_op={"--update": 7},
                                    stderr_override={"--update": "install failed"})
        self.assertTrue(result["failed"])
        self.assertTrue(result["changed"])
        self.assertTrue(result["partial"])
        self.assertEqual(result["rc"], 7)
        self.assertIn("install failed", result["stderr"])

    def test_post_verification_failure_reports_partial(self):
        installed = {"es-ES"}
        def runner(argv):
            if argv[1] == "--help":
                return 0, "--list --available --check --install --update --remove --dev", ""
            if argv[1] == "--list" and "--available" in argv:
                return 0, "es-ES\n", ""
            if argv[1] == "--check":
                return 0, "", ""
            if argv[1] == "--update":
                installed.clear()
                return 0, "", ""
            if argv[1] == "--list":
                return 0, "", ""
            return 0, "", ""
        FakeAnsibleModule.runner = runner
        FakeAnsibleModule.params = {"update": True}
        with self.assertRaises(ModuleExit) as raised:
            self.module.main()
        result = raised.exception.result
        self.assertTrue(result["failed"])
        self.assertTrue(result["changed"])
        self.assertTrue(result["partial"])
        self.assertFalse(result["installed"])

    def test_global_and_dev_lock_partition(self):
        self.assertNotEqual(self.module._lock_path(None), self.module._lock_path("dev1", "/tmp/dev1"))
        self.assertEqual(self.module._lock_path(None), "/run/lock/jmz-koha-translate-global.lock")
        self.assertEqual(self.module._lock_path("dev1", "/tmp/shared-tree"),
                         self.module._lock_path("dev2", "/tmp/shared-tree"))
        self.assertNotEqual(self.module._lock_path("dev1", "/tmp/dev1"),
                            self.module._lock_path("dev2", "/tmp/dev2"))

    def test_lock_released_on_error(self):
        self.module = load_module()
        with tempfile.NamedTemporaryFile() as lock:
            with self.assertRaises(self.module.TranslateError):
                with self.module._mutation_lock(lock.name, timeout=0):
                    raise self.module.TranslateError("boom")
            # Reopening and acquiring succeeds after the exceptional exit.
            with self.module._mutation_lock(lock.name, timeout=0):
                pass

    def test_lock_timeout_reports_conflict(self):
        import fcntl
        self.module = load_module()
        with tempfile.NamedTemporaryFile() as lock:
            holder = open(lock.name, "a", encoding="utf-8")
            fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                with self.assertRaises(self.module.TranslateError) as raised:
                    with self.module._mutation_lock(lock.name, timeout=0):
                        pass
                self.assertIn("timed out waiting", str(raised.exception))
            finally:
                fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
                holder.close()


if __name__ == "__main__":
    unittest.main()

