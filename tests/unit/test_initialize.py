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

    def __init__(self, **kwargs):
        self.params = dict(type(self).params)
        self.check_mode = type(self).check_mode
        self._diff = False

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
        spec.loader.exec_module(module)
    return module


def valid_params():
    return {
        "instance": "biblioteca", "state": "present", "language": "es-ES",
        "marc_flavour": "MARC21", "sample_data": [],
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
        "timeout": 1800, "_initialize_helper": "/tmp/helper.pl",
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

    def test_circulation_rule_names_normalize_common_case_and_spelling(self):
        fake = FakeAnsibleModule()
        fake.params["circulation_rules"][0]["rules"] = {
            "issueLength": 14, "lengthUnit": "days", "maxissuesqty": 5,
            "renewalSallowed": 2,
        }
        self.module._validate_params(fake)
        self.assertEqual(fake.params["circulation_rules"][0]["rules"], {
            "issuelength": 14, "lengthunit": "days", "maxissueqty": 5,
            "renewalsallowed": 2,
        })

    def test_inspect_does_not_require_onboarding_inputs(self):
        fake = FakeAnsibleModule()
        fake.params = {"instance": "biblioteca", "state": "inspect"}
        self.module._validate_params(fake)
        fake.params["administrator"] = {"password": "should-not-be-provided"}
        with self.assertRaisesRegex(self.module.InitializeError, "no acepta"):
            self.module._validate_params(fake)

    def test_instance_timezone_is_repaired_from_koha_conf(self):
        conf = os.path.join(ROOT, "tests/unit/fixtures/koha-conf-timezone.xml")
        os.makedirs(os.path.dirname(conf), exist_ok=True)
        with open(conf, "w", encoding="utf-8") as stream:
            stream.write("<yazgfs><timezone>America/Argentina/Buenos_Aires</timezone>"
                         "<database><hostname>localhost</hostname></database></yazgfs>")
        try:
            fake = mock.Mock()
            with mock.patch.object(self.module, "ensure_mariadb_timezone", return_value=True) as ensure:
                self.assertTrue(self.module._ensure_instance_timezone(fake, conf))
            ensure.assert_called_once_with(fake, "America/Argentina/Buenos_Aires", "localhost")
        finally:
            os.unlink(conf)

    def test_present_ensures_timezone_before_koha_state_probe(self):
        events = []
        lock = mock.Mock()
        lock.fileno.return_value = 9
        payloads = [
            {"state": "onboarding_required"},
            {"current_state": "initialized", "previous_state": "onboarding_required", "changed": True},
        ]

        def read_protocol(*_args, **_kwargs):
            events.append("koha")
            return payloads.pop(0)

        FakeAnsibleModule.params = valid_params()
        FakeAnsibleModule.params["circulation_rules"][0]["rules"] = {
            "issueLength": 14, "lengthUnit": "days", "maxissuesqty": 5,
            "renewalSallowed": 2,
        }
        with mock.patch.object(self.module.os.path, "isfile", return_value=True), \
             mock.patch.object(self.module.os.path, "islink", return_value=False), \
             mock.patch.object(self.module.os.path, "realpath", return_value="/tmp/initialize.pl"), \
             mock.patch.object(self.module.os, "access", return_value=True), \
             mock.patch.object(self.module.os, "geteuid", return_value=0), \
             mock.patch.object(self.module.os, "stat", return_value=mock.Mock(st_mode=self.module.stat.S_IRUSR)), \
             mock.patch.object(self.module.os, "open", return_value=9), \
             mock.patch.object(self.module.os, "fdopen", return_value=self.module.contextlib.nullcontext(lock)), \
             mock.patch.object(self.module.os.path, "isdir", return_value=True), \
             mock.patch.object(self.module, "_ensure_instance_timezone", side_effect=lambda *_: events.append("timezone") or True), \
             mock.patch.object(self.module, "_read_protocol", side_effect=read_protocol) as protocol_mock, \
             mock.patch.object(self.module.pwd, "getpwnam"), \
             mock.patch.object(self.module.fcntl, "flock"), \
             mock.patch.object(FakeAnsibleModule, "get_bin_path", return_value="/usr/sbin/koha-shell", create=True):
            with self.assertRaises(ModuleExit) as raised:
                self.module.main()

        self.assertEqual(events, ["timezone", "koha", "koha"])
        self.assertTrue(raised.exception.result["changed"])
        resume_request = protocol_mock.call_args_list[1].args[2]
        self.assertEqual(resume_request["operation"], "initialize")
        self.assertEqual(resume_request["circulation_rules"][0]["rules"], {
            "issuelength": 14, "lengthunit": "days", "maxissueqty": 5,
            "renewalsallowed": 2,
        })

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
