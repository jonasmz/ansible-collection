# SPDX-License-Identifier: MIT-0
"""Unit tests for translate using a simulated koha-translate CLI."""

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
    diff = False
    runner = None
    last = None

    def __init__(self, **kwargs):
        defaults = {"name": "es-ES", "state": "present", "update": False,
                    "verbose": False, "timeout": 600}
        defaults.update(type(self).params)
        self.params = defaults
        self.check_mode = type(self).check_mode
        self._diff = type(self).diff
        self.commands = []
        type(self).last = self

    def get_bin_path(self, name, required=False):
        return "/usr/sbin/koha-translate"

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
            mock.patch.object(self.module, "_mutation_lock", self.noop_lock()),
            mock.patch.object(self.module, "_run", self.fake_run),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def noop_lock():
        from contextlib import contextmanager

        @contextmanager
        def lock(*_args, **_kwargs):
            yield
        return lock

    @staticmethod
    def fake_run(argv, timeout):
        FakeAnsibleModule.last.commands.append(list(argv))
        return FakeAnsibleModule.runner(argv)

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

    def test_language_validator(self):
        for code in ("es", "es-ES", "zh-Hans-CN", "en-GB"):
            self.assertEqual(self.module.validate_language(code), code)
        for code in ("", "../es", "es_ES", "--help", "a/b", "éS"):
            with self.assertRaises(self.module.TranslateError):
                self.module.validate_language(code)

    def query(self, rc, stdout, stderr=""):
        with mock.patch.object(self.module, "_run", return_value=(rc, stdout, stderr)):
            return self.module._query_languages("/usr/sbin/koha-translate", "installed", 30)

    def test_exact_list_parsing_and_empty_list(self):
        codes, _ = self.query(0, "es-ES\nes-ES\nes-AR\n")
        self.assertEqual(codes, ["es-ES", "es-AR"])
        codes, _ = self.query(0, "")
        self.assertEqual(codes, [])
        # Koha exits 1 without output when no non-English translation is installed.
        codes, result = self.query(1, "")
        self.assertEqual((codes, result["rc"]), ([], 1))
        with self.assertRaises(self.module.TranslateError):
            self.query(0, "Installed languages:\n")
        with self.assertRaises(self.module.TranslateError):
            self.query(1, "", "boom")

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
        self.assertIn("no se puede quitar", result["msg"])

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

    def test_verbose_is_passed_through(self):
        FakeAnsibleModule.params = {"verbose": True}
        result, commands = self.run_module()
        self.assertTrue(result["changed"])
        self.assertIn(["/usr/sbin/koha-translate", "--install", "es-ES", "--verbose"], commands)

    def test_development_checkouts_are_no_longer_a_parameter(self):
        self.assertNotIn("dev_instance", self.module.main.__code__.co_names)
        self.assertFalse(hasattr(self.module, "_development_tree"))
        result, _ = self.run_module()
        self.assertNotIn("scope", result)
        self.assertNotIn("dev_instance", result)

    def test_unknown_unavailable_and_incomplete_po(self):
        result, _ = self.run_module(available=[])
        self.assertTrue(result["failed"])
        self.assertIn("no está disponible", result["msg"])
        result, _ = self.run_module(rc_by_op={"--check": 1}, stderr_override={"--check": "Error: x-pref.po not found"})
        self.assertTrue(result["failed"])
        self.assertIn("faltan archivos PO", result["msg"])

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

    def test_invalid_timeout_is_rejected_before_running_anything(self):
        FakeAnsibleModule.params = {"timeout": 0}
        result, commands = self.run_module()
        self.assertTrue(result["failed"])
        self.assertIn("timeout debe ser positivo", result["msg"])
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

    def test_failed_install_is_partial_too_and_reports_the_observed_state(self):
        result, _ = self.run_module(rc_by_op={"--install": 3}, stderr_override={"--install": "disk full"})
        self.assertTrue(result["failed"] and result["changed"] and result["partial"])
        self.assertEqual(result["action_executed"], "install")
        self.assertFalse(result["installed"])
        self.assertIn("disk full", result["stderr"])

    def test_timeout_kills_the_mutation_and_reports_partial(self):
        calls = []

        def runner(argv):
            calls.append(argv)
            if argv[1] == "--help":
                return 0, "--list --available --check --install --update --remove", ""
            if argv[1] == "--list" and "--available" in argv:
                return 0, "es-ES\n", ""
            if argv[1] == "--list":
                return 0, "", ""
            if argv[1] == "--check":
                return 0, "", ""
            raise self.module.CommandTimeout("half written", "")

        FakeAnsibleModule.runner = runner
        with self.assertRaises(ModuleExit) as raised:
            self.module.main()
        result = raised.exception.result
        self.assertTrue(result["failed"] and result["changed"] and result["partial"])
        self.assertIn("excedió el límite de 600 segundos", result["msg"])
        self.assertEqual(result["stdout"], "half written")
        self.assertFalse(result["installed"])

    def test_output_that_is_not_utf8_cannot_break_the_result(self):
        self.module = load_module()  # setUp replaced _run with the simulated CLI
        process = mock.Mock(returncode=0, pid=1)
        process.communicate.return_value = (b"Installation r\xe9ussie\n", b"warning \xff")
        with mock.patch.object(self.module.subprocess, "Popen", return_value=process):
            result = self.module._command(["koha-translate", "--install", "fr-FR"], "--install fr-FR", 30)
        for text in (result["stdout"], result["stderr"]):
            text.encode("utf-8")
        self.assertIn("r\ufffdussie", result["stdout"])
        self.assertEqual(self.module._bounded("lone \udce9 surrogate"), "lone ? surrogate")

    def test_run_kills_the_process_group_on_timeout(self):
        self.module = load_module()  # setUp replaced _run with the simulated CLI
        process = mock.Mock(pid=4321)
        process.communicate.side_effect = [self.module.subprocess.TimeoutExpired("koha-translate", 5), (b"partial", b"")]
        with mock.patch.object(self.module.subprocess, "Popen", return_value=process) as popen, \
                mock.patch.object(self.module.os, "killpg") as killpg:
            with self.assertRaises(self.module.CommandTimeout) as raised:
                self.module._run(["koha-translate", "--install", "es-ES"], 5)
        killpg.assert_called_once_with(4321, self.module.signal.SIGKILL)
        self.assertEqual(raised.exception.stdout, "partial")
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertEqual(popen.call_args.kwargs["env"]["LC_ALL"], "C")

    def test_mutations_share_one_global_lock_that_waits_a_bounded_time(self):
        self.module = load_module()
        captured = {}

        @__import__("contextlib").contextmanager
        def fake_lock(scope, name, message, wait=0):
            captured.update(scope=scope, name=name, wait=wait)
            yield

        with mock.patch.object(self.module, "exclusive_lock", fake_lock):
            with self.module._mutation_lock():
                pass
        self.assertEqual(captured, {"scope": "translate", "name": "global", "wait": self.module.LOCK_TIMEOUT})

    def test_a_busy_lock_is_reported_as_a_translate_error(self):
        self.module = load_module()

        @__import__("contextlib").contextmanager
        def busy(*_args, **_kwargs):
            raise self.module.ModuleInputError("lock ocupado")
            yield

        with mock.patch.object(self.module, "exclusive_lock", busy):
            with self.assertRaisesRegex(self.module.TranslateError, "lock ocupado"):
                with self.module._mutation_lock():
                    pass


if __name__ == "__main__":
    unittest.main()

