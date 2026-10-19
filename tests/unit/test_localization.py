# SPDX-License-Identifier: MIT-0
"""Unit tests for the localization module's validation and JSON protocol."""

import importlib.util
import json
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

    def __init__(self, **kwargs):
        self.params = {"instance": "biblioteca", "state": "present", "timeout": 120,
                       "_localization_helper": "/tmp/ansible-koha-localization-" + "a" * 32 + "/localization.pl"}
        self.params.update(type(self).params)
        self.check_mode = type(self).check_mode
        self._diff = type(self).diff

    def exit_json(self, **kwargs):
        raise ModuleExit(kwargs)

    def fail_json(self, **kwargs):
        kwargs.setdefault("failed", True)
        raise ModuleExit(kwargs)

    def get_bin_path(self, name, required=False):
        return "/usr/sbin/koha-shell"


def load_module():
    ansible = types.ModuleType("ansible")
    ansible_utils = types.ModuleType("ansible.module_utils")
    basic = types.ModuleType("ansible.module_utils.basic")
    basic.AnsibleModule = FakeAnsibleModule
    path = os.path.join(ROOT, "plugins/modules/localization.py")
    spec = importlib.util.spec_from_file_location("localization_test", path)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"ansible": ansible, "ansible.module_utils": ansible_utils,
                                      "ansible.module_utils.basic": basic}):
        spec.loader.exec_module(module)
    return module


class FakeProcess:
    pid = 123
    returncode = 0

    def __init__(self, payload, rc=0):
        self.payload = payload
        self.returncode = rc
        self.request = None

    def communicate(self, input=None, timeout=None):
        self.request = json.loads(input.decode("utf-8"))
        return self.payload, b"diagnostics go to stderr"


class LocalizationTest(unittest.TestCase):
    def setUp(self):
        FakeAnsibleModule.params = {}
        FakeAnsibleModule.check_mode = False
        FakeAnsibleModule.diff = False
        self.module = load_module()

    def test_instance_language_list_and_positions(self):
        self.assertEqual(self.module.validate_instance("koha-dev"), "koha-dev")
        for invalid in ("", "Upper", "../etc", "a" * 12, "has_under"):
            with self.assertRaises(self.module.LocalizationError):
                self.module.validate_instance(invalid)
        requested = self.module.validate_language_list(["es-ES", "en"], "staff_languages")
        self.assertEqual(requested, ["es-ES", "en"])
        for invalid in ([], ["en", "en"], ["es_ES"], [5], ["../en"]):
            with self.assertRaises(self.module.LocalizationError):
                self.module.validate_language_list(invalid, "opac_languages")
        for position in ("top", "footer", "both"):
            self.assertEqual(self.module.normalize_position(position), position)
        with self.assertRaises(self.module.LocalizationError):
            self.module.normalize_position("header")

    def test_partial_desired_settings_preserve_omitted_fields(self):
        self.assertEqual(self.module.build_desired({"opac_language_selector": True}),
                         {"opac_language_selector": True})
        self.assertEqual(self.module.build_desired({"staff_languages": ["es-ES", "en"]}),
                         {"staff_languages": ["es-ES", "en"]})
        with self.assertRaisesRegex(self.module.LocalizationError, "declare al menos"):
            self.module.build_desired({})

    def test_protocol_parsing_checks_structure_and_rc(self):
        process = FakeProcess(b'{"protocol":1,"ok":true,"koha_version":"26.05","before":{},"after":{},"updated_preferences":[],"staff_preference":"StaffInterfaceLanguages"}')
        with mock.patch.object(self.module.subprocess, "Popen", return_value=process) as popen:
            result = self.module._read_protocol(["koha-shell"], {"protocol": 1}, 30)
        self.assertTrue(result["ok"])
        self.assertEqual(popen.call_args.kwargs["start_new_session"], True)
        self.assertNotIn("shell", popen.call_args.kwargs)
        self.assertEqual(process.request, {"protocol": 1})
        for payload in (b"", b"not-json", b'{"protocol":99,"ok":true}', b'{"protocol":1}',
                        b'{"protocol":1,"ok":true}'):
            with mock.patch.object(self.module.subprocess, "Popen", return_value=FakeProcess(payload)):
                with self.assertRaises(self.module.LocalizationError):
                    self.module._read_protocol(["koha-shell"], {}, 30)
        with mock.patch.object(self.module.subprocess, "Popen", return_value=FakeProcess(
                b'{"protocol":1,"ok":false,"error":{"message":"Preference unavailable"}}', rc=1)):
            with self.assertRaisesRegex(self.module.LocalizationError, "Preference unavailable"):
                self.module._read_protocol(["koha-shell"], {}, 30)

    def test_helper_is_independently_packaged(self):
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "files/localization.pl")))
        with open(os.path.join(ROOT, "plugins/modules/localization.py"), encoding="utf-8") as stream:
            source = stream.read()
        self.assertNotIn("use C4::Context", source)
        self.assertIn("supports_check_mode=True", source)

    def test_perl_helper_has_separate_json_stdin_protocol(self):
        with open(os.path.join(ROOT, "files/localization.pl"), encoding="utf-8") as stream:
            helper = stream.read()
        self.assertIn("decode_json($input", helper)
        self.assertIn("C4::Context->set_preference", helper)
        self.assertIn("getTranslatedLanguages", helper)
        self.assertNotIn("UPDATE systempreferences", helper)

    def test_main_reports_planned_diff_and_idempotent_result(self):
        params = {"instance": "biblioteca", "staff_languages": ["es-ES", "en"],
                  "opac_languages": ["es-ES", "en"], "timeout": 120,
                  "_localization_helper": "/tmp/ansible-koha-localization-" + "a" * 32 + "/localization.pl"}
        FakeAnsibleModule.params = params
        FakeAnsibleModule.check_mode = True
        FakeAnsibleModule.diff = True
        projected = {"koha_version": "26.05.04.000", "staff_preference": "StaffInterfaceLanguages",
                     "before": {"staff_languages": ["en"], "opac_languages": ["en"]},
                     "after": {"staff_languages": ["es-ES", "en"], "opac_languages": ["es-ES", "en"]},
                     "updated_preferences": ["StaffInterfaceLanguages", "OPACLanguages"]}
        calls = []
        with mock.patch.object(self.module.os.path, "isfile", return_value=True), \
                mock.patch.object(self.module.os.path, "realpath", side_effect=lambda path: path), \
                mock.patch.object(self.module.os.path, "islink", return_value=False), \
                mock.patch.object(self.module.os, "access", return_value=True), \
                mock.patch.object(self.module.os, "geteuid", return_value=0), \
                mock.patch.object(self.module.os, "stat", return_value=types.SimpleNamespace(st_mode=0o400)), \
                mock.patch.object(self.module.pwd, "getpwnam", return_value=object()), \
                mock.patch.object(self.module, "_read_protocol", side_effect=lambda command, request, timeout: calls.append((command, request)) or projected):
            with self.assertRaises(ModuleExit) as raised:
                self.module.main()
        result = raised.exception.result
        self.assertTrue(result["changed"])
        self.assertTrue(result["planned"])
        self.assertEqual(result["diff"]["before"], projected["before"])
        self.assertFalse(calls[0][1]["apply"])

        FakeAnsibleModule.check_mode = False
        FakeAnsibleModule.diff = False
        projected["updated_preferences"] = []
        with mock.patch.object(self.module.os.path, "isfile", return_value=True), \
                mock.patch.object(self.module.os.path, "realpath", side_effect=lambda path: path), \
                mock.patch.object(self.module.os.path, "islink", return_value=False), \
                mock.patch.object(self.module.os, "access", return_value=True), \
                mock.patch.object(self.module.os, "geteuid", return_value=0), \
                mock.patch.object(self.module.os, "stat", return_value=types.SimpleNamespace(st_mode=0o400)), \
                mock.patch.object(self.module.pwd, "getpwnam", return_value=object()), \
                mock.patch.object(self.module, "_read_protocol", return_value=projected):
            with self.assertRaises(ModuleExit) as raised:
                self.module.main()
        self.assertFalse(raised.exception.result["changed"])
        self.assertFalse(raised.exception.result["planned"])


if __name__ == "__main__":
    unittest.main()
