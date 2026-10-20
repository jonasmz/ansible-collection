# SPDX-License-Identifier: MIT-0
import importlib.util
import json
import os
import subprocess
import sys
import types
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
HELPER_SPEC = importlib.util.spec_from_file_location(
    "koha_instance_helper_test", os.path.join(ROOT, "plugins/module_utils/koha_instance.py")
)
KOHA_HELPER = importlib.util.module_from_spec(HELPER_SPEC)
HELPER_SPEC.loader.exec_module(KOHA_HELPER)


class ModuleExit(Exception):
    def __init__(self, result):
        self.result = result


class FakeAnsibleModule:
    params = {}
    check_mode = False

    diff = False

    spec = {}

    def __init__(self, **kwargs):
        self.params = dict(type(self).params)
        self.check_mode = type(self).check_mode
        self._diff = type(self).diff
        type(self).spec = kwargs

    def exit_json(self, **kwargs):
        raise ModuleExit(kwargs)

    def fail_json(self, **kwargs):
        raise ModuleExit(kwargs)


class FakeProcess:
    pid = 4321
    returncode = 0

    def __init__(self, stdout=b'{"protocol":1,"ok":true}', stderr=b"", timeout=False):
        self.stdout = stdout
        self.stderr = stderr
        self.timeout = timeout
        self.inputs = []

    def communicate(self, input=None, timeout=None):
        self.inputs.append((input, timeout))
        if self.timeout:
            self.timeout = False
            raise subprocess.TimeoutExpired("koha-shell", timeout)
        return self.stdout, self.stderr


def load_module():
    ansible = types.ModuleType("ansible")
    ansible_utils = types.ModuleType("ansible.module_utils")
    basic = types.ModuleType("ansible.module_utils.basic")
    basic.AnsibleModule = FakeAnsibleModule
    collections = types.ModuleType("ansible_collections")
    jmz = types.ModuleType("ansible_collections.jmz")
    koha = types.ModuleType("ansible_collections.jmz.koha")
    plugins = types.ModuleType("ansible_collections.jmz.koha.plugins")
    module_utils = types.ModuleType("ansible_collections.jmz.koha.plugins.module_utils")
    module_utils.koha_instance = KOHA_HELPER
    module_map = {
        "ansible": ansible, "ansible.module_utils": ansible_utils,
        "ansible.module_utils.basic": basic,
        "ansible_collections": collections, "ansible_collections.jmz": jmz,
        "ansible_collections.jmz.koha": koha,
        "ansible_collections.jmz.koha.plugins": plugins,
        "ansible_collections.jmz.koha.plugins.module_utils": module_utils,
        "ansible_collections.jmz.koha.plugins.module_utils.koha_instance": KOHA_HELPER,
    }
    spec = importlib.util.spec_from_file_location(
        "initialize_module_test", os.path.join(ROOT, "plugins/modules/initialize.py")
    )
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, module_map):
        lock_spec = importlib.util.spec_from_file_location(
            "koha_lock_test", os.path.join(ROOT, "plugins/module_utils/koha_lock.py"))
        lock_helper = importlib.util.module_from_spec(lock_spec)
        lock_spec.loader.exec_module(lock_helper)
        sys.modules["ansible_collections.jmz.koha.plugins.module_utils.koha_lock"] = lock_helper
        spec.loader.exec_module(module)
    return module


HELPER = "/tmp/ansible-koha-initialize-%s/initialize.pl" % ("a" * 32)


def valid_params():
    return {
        "instance": "biblioteca", "state": "present", "language": "es-ES",
        "marcflavor": "marc21", "sample_data": [],
        "library": {"code": "CENTRAL", "name": "Biblioteca Central"},
        "patron_categories": [
            {"code": "STAFF", "description": "Personal", "type": "S", "enrolment_period": 1,
             "default_privacy": "default"},
            {"code": "ADULT", "description": "Adultos", "type": "A", "enrolment_period": 1,
             "default_privacy": "default"},
        ],
        "administrator": {"username": "admin", "firstname": "Ada", "surname": "Koha",
                          "cardnumber": "A-001", "library": "CENTRAL", "category": "STAFF",
                          "password": "vault-secret"},
        "item_types": [{"code": "BOOK", "description": "Libros"}],
        "circulation_rules": [{"library": "CENTRAL", "category": "ADULT", "item_type": "BOOK",
                               "rules": {"issuelength": 14}}],
        "timeout": 1800, "_initialize_helper": HELPER,
    }


class InitializeModuleTest(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        FakeAnsibleModule.params = valid_params()
        FakeAnsibleModule.check_mode = False

    def test_identifier_and_cross_reference_validation(self):
        fake = FakeAnsibleModule()
        self.module._validate_params(fake)
        fake.params["instance"] = "../../other"
        with self.assertRaisesRegex(self.module.InitializeError, "instance"):
            self.module._validate_params(fake)
        fake.params = valid_params()
        fake.params["administrator"]["category"] = "ADULT"
        with self.assertRaisesRegex(self.module.InitializeError, "tipo S"):
            self.module._validate_params(fake)

    def test_optional_data_ids_reject_path_traversal(self):
        fake = FakeAnsibleModule()
        fake.params["sample_data"] = ["../../etc/passwd.sql"]
        with self.assertRaisesRegex(self.module.InitializeError, "sample_data"):
            self.module._validate_params(fake)

    def test_language_code_rejects_path_traversal(self):
        fake = FakeAnsibleModule()
        fake.params["language"] = "../../etc"
        with self.assertRaisesRegex(self.module.InitializeError, "language"):
            self.module._validate_params(fake)

    def test_circulation_rule_names_normalize_case(self):
        fake = FakeAnsibleModule()
        fake.params["circulation_rules"][0]["rules"] = {"issueLength": 14, "lengthUnit": "days", "renewalSallowed": 2}
        self.module._validate_params(fake)
        self.assertEqual(fake.params["circulation_rules"][0]["rules"],
                         {"issuelength": 14, "lengthunit": "days", "renewalsallowed": 2})

    def test_inspect_does_not_require_onboarding_inputs(self):
        fake = FakeAnsibleModule()
        fake.params = {"instance": "biblioteca", "state": "inspect"}
        self.module._validate_params(fake)
        fake.params["administrator"] = {"password": "should-not-be-provided"}
        with self.assertRaisesRegex(self.module.InitializeError, "no acepta"):
            self.module._validate_params(fake)

    def test_circulation_rule_names_are_lowercased_and_typo_alias_is_gone(self):
        fake = FakeAnsibleModule()
        fake.params["circulation_rules"][0]["rules"] = {"issueLength": 14, "maxissueqty": 5}
        self.module._validate_params(fake)
        self.assertEqual(fake.params["circulation_rules"][0]["rules"], {"issuelength": 14, "maxissueqty": 5})
        fake.params["circulation_rules"][0]["rules"] = {"maxissuesqty": 5}
        self.module._validate_params(fake)
        self.assertEqual(list(fake.params["circulation_rules"][0]["rules"]), ["maxissuesqty"])

    def test_duplicates_and_non_scalar_rule_values_are_rejected(self):
        cases = (
            ("patron_categories", lambda p: p["patron_categories"].append(dict(p["patron_categories"][0], description="Otra")), "patron_categories contiene códigos repetidos"),
            ("item_types", lambda p: p["item_types"].append({"code": "BOOK", "description": "Otra"}), "item_types contiene códigos repetidos"),
            ("scope", lambda p: p["circulation_rules"].append(dict(p["circulation_rules"][0])), "repite el ámbito"),
            ("dict value", lambda p: p["circulation_rules"][0]["rules"].update(issuelength={"a": 1}), "texto, número o booleano"),
            ("list value", lambda p: p["circulation_rules"][0]["rules"].update(issuelength=[1]), "texto, número o booleano"),
            ("case duplicate", lambda p: p["circulation_rules"][0]["rules"].update(IssueLength=7), "nombres duplicados"),
        )
        for name, mutate, message in cases:
            with self.subTest(name):
                fake = FakeAnsibleModule()
                fake.params = valid_params()
                mutate(fake.params)
                with self.assertRaisesRegex(self.module.InitializeError, message):
                    self.module._validate_params(fake)

    def test_explicit_null_onboarding_parameters_are_rejected_not_crashed(self):
        for name in ("language", "marcflavor", "library", "patron_categories", "administrator", "item_types", "circulation_rules"):
            with self.subTest(name=name):
                fake = FakeAnsibleModule()
                fake.params = dict(valid_params(), **{name: None})
                with self.assertRaisesRegex(self.module.InitializeError, "%s es obligatorio" % name):
                    self.module._validate_params(fake)

    def test_inspect_rejects_every_onboarding_parameter(self):
        for extra in ({"language": "en"}, {"marcflavor": "marc21"}, {"sample_data": ["x/y.sql"]},
                      {"library": {"code": "A", "name": "B"}}):
            with self.subTest(extra=extra):
                fake = FakeAnsibleModule()
                fake.params = dict({"instance": "biblioteca", "state": "inspect", "sample_data": []}, **extra)
                with self.assertRaisesRegex(self.module.InitializeError, "no acepta"):
                    self.module._validate_params(fake)

    def test_argument_spec_requires_onboarding_for_present_and_has_no_legacy_aliases(self):
        self.module.main.__globals__["AnsibleModule"] = FakeAnsibleModule
        FakeAnsibleModule.params = valid_params()
        with self.assertRaises(Exception):
            self.module.main()
        spec = FakeAnsibleModule.spec
        self.assertEqual(spec["required_if"][0][:2], ("state", "present"))
        self.assertEqual(set(spec["required_if"][0][2]),
                         {"language", "marcflavor", "library", "patron_categories", "administrator", "item_types", "circulation_rules"})
        arguments = spec["argument_spec"]
        self.assertNotIn("aliases", arguments["marcflavor"])
        self.assertEqual(arguments["marcflavor"]["choices"], ["marc21", "unimarc"])
        self.assertFalse(arguments["administrator"].get("no_log"))
        self.assertTrue(arguments["administrator"]["options"]["password"]["no_log"])

    def test_marc_flavour_is_sent_to_koha_in_uppercase(self):
        requests = []

        def read_protocol(_module, _command, request, _timeout):
            requests.append(request)
            return {"state": "onboarding_required"} if request["operation"] == "inspect" else {"current_state": "initialized"}

        self._run_with_protocol(read_protocol)
        self.assertEqual(requests[1]["marc_flavour"], "MARC21")

    def test_no_helper_json_surfaces_scrubbed_stderr_and_timezone_hint(self):
        stderr = b"Can't locate Koha/Foo.pm\x07 secret-pass\nUnknown or incorrect time zone: 'Europe/Madrid'"
        process = FakeProcess(stdout=b"", stderr=stderr)
        process.returncode = 2
        request = {"protocol": 1, "operation": "inspect", "administrator": {"password": "secret-pass"}}
        with mock.patch.object(self.module.subprocess, "Popen", return_value=process):
            with self.assertRaises(self.module.InitializeError) as raised:
                self.module._read_protocol(mock.Mock(), ["koha-shell"], request, 3)
        message = str(raised.exception)
        self.assertIn("Can't locate Koha/Foo.pm", message)
        self.assertNotIn("secret-pass", message)
        self.assertNotIn("\x07", message)
        self.assertIn("jmz.koha.mariadb_timezone", message)
        self.assertTrue(raised.exception.details["indeterminate"])

    def test_helper_reported_timezone_error_gets_the_same_hint(self):
        failed = FakeProcess(stdout=b'{"protocol":1,"ok":false,"error":{"type":"koha_operation_failed","message":"Unknown or incorrect time zone: x"}}')
        failed.returncode = 2
        with mock.patch.object(self.module.subprocess, "Popen", return_value=failed):
            with self.assertRaisesRegex(self.module.InitializeError, "mariadb_timezone"):
                self.module._read_protocol(mock.Mock(), ["koha-shell"], {"protocol": 1}, 3)

    def run_main(self, protocol, diff=False):
        """Run main() with the Koha host mocked; ``protocol`` answers or raises per helper call."""
        FakeAnsibleModule.params = valid_params()
        FakeAnsibleModule.diff = diff
        calls = []

        def read_protocol(_module, _command, request, _timeout):
            calls.append(request["operation"])
            answer = protocol.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        self.addCleanup(setattr, FakeAnsibleModule, "diff", False)
        return self._run_with_protocol(read_protocol), calls

    def _run_with_protocol(self, read_protocol):
        with mock.patch.object(self.module.os.path, "isfile", return_value=True), \
             mock.patch.object(self.module.os.path, "islink", return_value=False), \
             mock.patch.object(self.module.os.path, "realpath", side_effect=lambda path: path), \
             mock.patch.object(self.module.os, "access", return_value=True), \
             mock.patch.object(self.module.os, "geteuid", return_value=0), \
             mock.patch.object(self.module.os, "stat", return_value=mock.Mock(st_mode=self.module.stat.S_IRUSR)), \
             mock.patch.object(self.module, "exclusive_lock", side_effect=lambda *_: self.module.contextlib.nullcontext()), \
             mock.patch.object(self.module.os.path, "isdir", return_value=True), \
             mock.patch.object(self.module, "_read_protocol", side_effect=read_protocol), \
             mock.patch.object(self.module.pwd, "getpwnam"), \
             mock.patch.object(FakeAnsibleModule, "get_bin_path", return_value="/usr/sbin/koha-shell", create=True):
            with self.assertRaises(ModuleExit) as raised:
                self.module.main()
        return raised.exception.result

    def indeterminate(self, message):
        return self.module.InitializeError(message, {"indeterminate": True})

    def test_timeout_during_initialize_reports_the_state_it_left_behind(self):
        result, calls = self.run_main([{"state": "uninitialized"}, self.indeterminate("koha-shell excedió el límite de 1800 segundos"),
                                       {"state": "onboarding_required"}])
        self.assertEqual(calls, ["inspect", "initialize", "inspect"])
        self.assertTrue(result["changed"] and result["partial"])
        self.assertEqual((result["previous_state"], result["current_state"]), ("uninitialized", "onboarding_required"))
        self.assertIn("observado tras el fallo: onboarding_required", result["msg"])

    def test_invalid_helper_output_without_state_change_is_not_reported_as_a_change(self):
        result, _ = self.run_main([{"state": "onboarding_required"}, self.indeterminate("El helper Perl no devolvió JSON válido (rc=2)"),
                                   {"state": "onboarding_required"}])
        self.assertFalse(result["changed"])
        self.assertFalse(result["partial"])
        self.assertEqual(result["current_state"], "onboarding_required")

    def test_failure_that_cannot_be_observed_is_reported_conservatively(self):
        result, _ = self.run_main([{"state": "uninitialized"}, self.indeterminate("koha-shell excedió el límite"),
                                   self.module.InitializeError("sin conexión")])
        self.assertTrue(result["changed"] and result["partial"])
        self.assertIn("No se pudo determinar", result["msg"])

    def test_failure_reported_by_the_helper_is_trusted_without_a_second_probe(self):
        failure = self.module.InitializeError("koha_operation_failed: boom", {
            "changed": True, "partial": True, "phase": "onboarding", "actions": ["schema_created"],
            "previous_state": "uninitialized", "current_state": "onboarding_required"})
        result, calls = self.run_main([{"state": "uninitialized"}, failure])
        self.assertEqual(calls, ["inspect", "initialize"])
        self.assertEqual((result["actions"], result["phase"], result["partial"]), (["schema_created"], "onboarding", True))

    def test_check_mode_asks_the_helper_for_a_dry_run_and_reports_its_plan(self):
        FakeAnsibleModule.check_mode = True
        self.addCleanup(setattr, FakeAnsibleModule, "check_mode", False)
        requests = []
        plan = {"changed": True, "complete": True, "actions": ["item_type_created:DVD"], "state_info": {"item_types": 1}}

        def read_protocol(_module, _command, request, _timeout):
            requests.append(request)
            return {"state": "initialized"} if request["operation"] == "inspect" else plan

        FakeAnsibleModule.params = valid_params()
        result = self._run_with_protocol(read_protocol)
        self.assertEqual([r["operation"] for r in requests], ["inspect", "initialize"])
        self.assertIs(requests[1]["apply"], False)
        self.assertTrue(result["changed"] and result["planned"])
        self.assertFalse(result["partial"])
        self.assertEqual((result["actions"], result["previous_state"], result["current_state"]),
                         (["item_type_created:DVD"], "initialized", "initialized"))

    def test_check_mode_before_the_installer_ran_is_an_incomplete_plan(self):
        FakeAnsibleModule.check_mode = True
        self.addCleanup(setattr, FakeAnsibleModule, "check_mode", False)
        plan = {"changed": True, "complete": False, "actions": ["schema_created", "initial_data_loaded"]}
        result = self._run_with_protocol(lambda _m, _c, request, _t: {"state": "uninitialized"} if request["operation"] == "inspect" else plan)
        self.assertTrue(result["changed"] and result["partial"])
        self.assertIn("no se puede simular", result["msg"])

    def test_check_mode_with_nothing_to_do_reports_no_change(self):
        FakeAnsibleModule.check_mode = True
        self.addCleanup(setattr, FakeAnsibleModule, "check_mode", False)
        plan = {"changed": False, "complete": True, "actions": []}
        result = self._run_with_protocol(lambda _m, _c, request, _t: {"state": "initialized"} if request["operation"] == "inspect" else plan)
        self.assertFalse(result["changed"])
        self.assertEqual(result["actions"], [])

    def test_real_run_asks_the_helper_to_apply(self):
        requests = []

        def read_protocol(_module, _command, request, _timeout):
            requests.append(request)
            return {"state": "onboarding_required"} if request["operation"] == "inspect" else {"current_state": "initialized"}

        FakeAnsibleModule.params = valid_params()
        self._run_with_protocol(read_protocol)
        self.assertIs(requests[1]["apply"], True)

    def test_helper_path_must_be_the_staged_one(self):
        FakeAnsibleModule.params = dict(valid_params(), _initialize_helper="/tmp/evil/initialize.pl")
        result = self._run_with_protocol(lambda *_: {"state": "initialized"})
        self.assertIn("helper Perl temporal", result["msg"])

    def test_success_returns_diff_only_when_requested(self):
        answers = lambda: [{"state": "onboarding_required"}, {"current_state": "initialized", "previous_state": "onboarding_required",
                                                             "changed": True, "actions": ["library_created:CENTRAL"]}]
        plain, _ = self.run_main(answers())
        self.assertNotIn("diff", plain)
        with_diff, _ = self.run_main(answers(), diff=True)
        self.assertEqual(with_diff["diff"], {"before": "onboarding_required", "after": "initialized"})
        self.assertEqual(with_diff["actions"], ["library_created:CENTRAL"])

    def test_protocol_failures_without_a_usable_answer_are_marked_indeterminate(self):
        with mock.patch.object(self.module.subprocess, "Popen", return_value=FakeProcess(timeout=True)), \
             mock.patch.object(self.module.os, "killpg"):
            with self.assertRaises(self.module.InitializeError) as raised:
                self.module._read_protocol(mock.Mock(), ["koha-shell"], {}, 3)
        self.assertTrue(raised.exception.details["indeterminate"])
        with mock.patch.object(self.module.subprocess, "Popen", return_value=FakeProcess(stdout=b"warning only")):
            with self.assertRaises(self.module.InitializeError) as raised:
                self.module._read_protocol(mock.Mock(), ["koha-shell"], {}, 3)
        self.assertTrue(raised.exception.details["indeterminate"])
        failed = FakeProcess(stdout=b'{"protocol":1,"ok":false,"error":{"type":"koha_operation_failed","message":"boom","details":{"changed":true}}}')
        failed.returncode = 2
        with mock.patch.object(self.module.subprocess, "Popen", return_value=failed):
            with self.assertRaises(self.module.InitializeError) as raised:
                self.module._read_protocol(mock.Mock(), ["koha-shell"], {}, 3)
        self.assertNotIn("indeterminate", raised.exception.details)

    def test_protocol_validates_json_rc_and_protocol_version(self):
        process = FakeProcess()
        with mock.patch.object(self.module.subprocess, "Popen", return_value=process) as popen:
            payload = self.module._read_protocol(mock.Mock(), ["/usr/sbin/koha-shell", "biblioteca", "-c", "perl /tmp/helper.pl"],
                                                 {"protocol": 1, "operation": "inspect"}, 30)
        self.assertTrue(payload["ok"])
        self.assertEqual(popen.call_args.args[0][0], "/usr/sbin/koha-shell")
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertNotIn("shell", popen.call_args.kwargs)
        self.assertEqual(process.inputs[0][1], 30)

        bad = FakeProcess(stdout=b'{"protocol":99,"ok":true}')
        with mock.patch.object(self.module.subprocess, "Popen", return_value=bad):
            with self.assertRaisesRegex(self.module.InitializeError, "protocolo"):
                self.module._read_protocol(mock.Mock(), ["koha-shell"], {}, 30)

    def test_protocol_keeps_secret_in_stdin_and_not_argv(self):
        request = {"protocol": 1, "operation": "initialize", "administrator": {"password": "secret-value"}}
        process = FakeProcess()
        with mock.patch.object(self.module.subprocess, "Popen", return_value=process) as run:
            self.module._read_protocol(mock.Mock(), ["koha-shell", "biblioteca", "-c", "perl /tmp/initialize.pl"], request, 5)
        self.assertNotIn("secret-value", " ".join(run.call_args.args[0]))
        self.assertIn(b"secret-value", process.inputs[0][0])

    def test_timeout_and_invalid_json_fail_closed(self):
        process = FakeProcess(timeout=True)
        with mock.patch.object(self.module.subprocess, "Popen", return_value=process), \
             mock.patch.object(self.module.os, "killpg") as killpg:
            with self.assertRaisesRegex(self.module.InitializeError, "límite"):
                self.module._read_protocol(mock.Mock(), ["koha-shell"], {}, 3)
            killpg.assert_called_once_with(process.pid, self.module.signal.SIGKILL)
        completed = FakeProcess(stdout=b"warning only")
        with mock.patch.object(self.module.subprocess, "Popen", return_value=completed):
            with self.assertRaisesRegex(self.module.InitializeError, "JSON válido"):
                self.module._read_protocol(mock.Mock(), ["koha-shell"], {}, 3)


if __name__ == "__main__":
    unittest.main()
