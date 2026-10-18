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
    spec = importlib.util.spec_from_file_location(
        "initialize_module_test", os.path.join(ROOT, "plugins/modules/initialize.py")
    )
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"ansible": ansible, "ansible.module_utils": ansible_utils,
                                      "ansible.module_utils.basic": basic}):
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

    def test_inspect_does_not_require_onboarding_inputs(self):
        fake = FakeAnsibleModule()
        fake.params = {"instance": "biblioteca", "state": "inspect"}
        self.module._validate_params(fake)
        fake.params["administrator"] = {"password": "should-not-be-provided"}
        with self.assertRaisesRegex(self.module.InitializeError, "no acepta"):
            self.module._validate_params(fake)

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
