# SPDX-License-Identifier: MIT-0
import contextlib
import importlib.util
import json
import os
import re
import sys
import types
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
HELPER = "/tmp/ansible-koha-smtp-%s/smtp.pl" % ("a" * 32)


class ModuleExit(Exception):
    def __init__(self, result):
        self.result = result


class FakeAnsibleModule:
    params = {}
    check_mode = False

    def __init__(self, **kwargs):
        self.params = dict(type(self).params)
        self.check_mode = type(self).check_mode
        self._diff = True

    def exit_json(self, **kwargs):
        raise ModuleExit(kwargs)

    def fail_json(self, **kwargs):
        raise ModuleExit(dict(kwargs, failed=True))

    def get_bin_path(self, name, required=False):
        return "/usr/sbin/" + name


def load_module():
    ansible = types.ModuleType("ansible")
    ansible_utils = types.ModuleType("ansible.module_utils")
    basic = types.ModuleType("ansible.module_utils.basic")
    basic.AnsibleModule = FakeAnsibleModule
    spec = importlib.util.spec_from_file_location("smtp_module_test", os.path.join(ROOT, "plugins/modules/smtp.py"))
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"ansible": ansible, "ansible.module_utils": ansible_utils,
                                      "ansible.module_utils.basic": basic}):
        spec.loader.exec_module(module)
    return module


def params(**server):
    values = {"name": "Notificaciones", "host": "smtp.example.org", "port": 587, "smtp_timeout": 120,
              "ssl_mode": "starttls", "user_name": "", "password": "", "debug": False}
    values.update(server)
    return {"instance": "biblioteca", "server": values, "timeout": 60, "_smtp_helper": HELPER}


def helper_reply(**overrides):
    reply = {"protocol": 1, "ok": True, "changed": True, "created": True, "updated": False, "promoted": True,
             "server_id": 7, "previous_default": None, "before": None,
             "after": {"name": "Notificaciones", "host": "smtp.example.org", "is_default": True}}
    reply.update(overrides)
    return reply


class SmtpModuleTest(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def validate(self, **server):
        self.module._validate(params(**server))

    def test_instance_validation_rejects_traversal_and_injection(self):
        for instance in ("../other", "library;touch /tmp/pwned", "A", "a" * 12):
            with self.subTest(instance=instance), self.assertRaises(self.module.SmtpError):
                self.module._validate(dict(params(), instance=instance))

    def test_server_validation(self):
        self.validate()
        self.validate(host="10.0.0.5", password="")
        for bad, message in ((dict(port=65536), "port"), (dict(port=True), "port"), (dict(smtp_timeout=0), "smtp_timeout"),
                             (dict(host="smtp.example;id"), "host"), (dict(ssl_mode="tls"), "ssl_mode"),
                             (dict(name="  "), "name"), (dict(name="a\nb"), "name"),
                             (dict(user_name="a\nb"), "user_name"), (dict(password="a\x00b"), "password")):
            with self.subTest(bad=bad), self.assertRaisesRegex(self.module.SmtpError, message):
                self.validate(**bad)

    def run_main(self, reply=None, check_mode=False, **overrides):
        FakeAnsibleModule.params = dict(params(), **overrides)
        FakeAnsibleModule.check_mode = check_mode
        calls = []

        def fake_read(command, request, timeout):
            calls.append((command, request))
            return reply or helper_reply()

        self.locks = []

        @contextlib.contextmanager
        def fake_lock(instance):
            self.locks.append(instance)
            yield

        patches = (mock.patch.object(self.module, "_read_protocol", fake_read),
                   mock.patch.object(self.module, "_instance_lock", fake_lock),
                   mock.patch.object(self.module.os, "geteuid", return_value=0),
                   mock.patch.object(self.module.pwd, "getpwnam"),
                   mock.patch.object(self.module.os.path, "isfile", return_value=True),
                   mock.patch.object(self.module.os.path, "islink", return_value=False),
                   mock.patch.object(self.module.os.path, "realpath", side_effect=lambda p: p),
                   mock.patch.object(self.module.os, "access", return_value=True),
                   mock.patch.object(self.module.os, "stat", return_value=mock.Mock(st_mode=0o100644)))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        with self.assertRaises(ModuleExit) as raised:
            self.module.main()
        return raised.exception.result, calls

    def test_request_carries_full_server_and_applies(self):
        result, calls = self.run_main()
        command, request = calls[0]
        self.assertEqual(command, ["/usr/sbin/koha-shell", "biblioteca", "-c", "perl %s" % HELPER])
        self.assertTrue(request["apply"])
        self.assertEqual(request["desired"]["name"], "Notificaciones")
        self.assertEqual(request["desired"]["debug"], 0)
        # Koha's column is called timeout; the module parameter is smtp_timeout.
        self.assertEqual(request["desired"]["timeout"], 120)
        self.assertNotIn("smtp_timeout", request["desired"])
        self.assertEqual(self.locks, ["biblioteca"])
        self.assertTrue(result["changed"] and result["created"] and result["promoted"])
        self.assertEqual(result["server_id"], 7)

    def test_check_mode_does_not_apply(self):
        _, calls = self.run_main(check_mode=True)
        self.assertFalse(calls[0][1]["apply"])
        self.assertEqual(self.locks, [])

    def test_noop_reports_unchanged(self):
        result, _ = self.run_main(reply=helper_reply(changed=False, created=False, promoted=False))
        self.assertFalse(result["changed"])
        self.assertNotIn("failed", result)

    def test_previous_default_is_reported(self):
        result, _ = self.run_main(reply=helper_reply(previous_default={"id": 1, "name": "Antiguo"}))
        self.assertEqual(result["previous_default"], {"id": 1, "name": "Antiguo"})

    def test_requires_root(self):
        with mock.patch.object(self.module.os, "geteuid", return_value=1000):
            FakeAnsibleModule.params = params()
            with self.assertRaises(ModuleExit) as raised:
                self.module.main()
        self.assertIn("become", raised.exception.result["msg"])

    def test_rejects_untrusted_helper_path(self):
        result, _ = self.run_main(_smtp_helper="/tmp/evil/smtp.pl")
        self.assertTrue(result["failed"])

    def test_protocol_rejects_malformed_helper_output(self):
        process = mock.Mock(returncode=0)
        process.communicate.return_value = (json.dumps({"protocol": 1, "ok": True}).encode(), b"")
        with mock.patch.object(self.module.subprocess, "Popen", return_value=process):
            with self.assertRaisesRegex(self.module.SmtpError, "incompleta"):
                self.module._read_protocol(["x"], {}, 5)

    def test_error_after_commit_reports_changed(self):
        for committed, expected in ((True, True), (False, False)):
            process = mock.Mock(returncode=1)
            process.communicate.return_value = (json.dumps(
                {"protocol": 1, "ok": False, "committed": committed, "error": {"message": "verificación"}}).encode(), b"")
            with mock.patch.object(self.module.subprocess, "Popen", return_value=process):
                with self.assertRaises(self.module.SmtpError) as raised:
                    self.module._read_protocol(["x"], {}, 5)
            self.assertIs(raised.exception.changed, expected)

    def test_failed_run_passes_changed_to_fail_json(self):
        def committed_failure(command, request, timeout):
            raise self.module.SmtpError("verificación", changed=True)
        FakeAnsibleModule.params = params()
        FakeAnsibleModule.check_mode = False
        with mock.patch.object(self.module, "_read_protocol", committed_failure), \
                mock.patch.object(self.module, "_instance_lock", lambda i: contextlib.nullcontext()), \
                mock.patch.object(self.module.os, "geteuid", return_value=0), \
                mock.patch.object(self.module.pwd, "getpwnam"), \
                mock.patch.object(self.module.os.path, "isfile", return_value=True), \
                mock.patch.object(self.module.os.path, "islink", return_value=False), \
                mock.patch.object(self.module.os.path, "realpath", side_effect=lambda p: p), \
                mock.patch.object(self.module.os, "access", return_value=True), \
                mock.patch.object(self.module.os, "stat", return_value=mock.Mock(st_mode=0o100644)):
            with self.assertRaises(ModuleExit) as raised:
                self.module.main()
        self.assertTrue(raised.exception.result["failed"])
        self.assertTrue(raised.exception.result["changed"])

    def test_protocol_surfaces_koha_errors(self):
        process = mock.Mock(returncode=1)
        process.communicate.return_value = (json.dumps(
            {"protocol": 1, "ok": False, "error": {"message": "Koha is not initialized"}}).encode(), b"")
        with mock.patch.object(self.module.subprocess, "Popen", return_value=process):
            with self.assertRaisesRegex(self.module.SmtpError, "not initialized"):
                self.module._read_protocol(["x"], {}, 5)


class SmtpScopeTest(unittest.TestCase):
    """The module must stay limited to adding a default SMTP server."""

    def test_module_does_not_touch_koha_conf_or_other_settings(self):
        for path in ("plugins/modules/smtp.py", "files/smtp.pl"):
            with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
                source = handle.read()
            code = re.sub(r"(?s)(DOCUMENTATION|EXAMPLES|RETURN) = r'''.*?'''", "", source)
            for forbidden in ("os.replace", "koha-email", "koha-preferences", "KohaAdminEmailAddress", "email.enabled"):
                self.assertNotIn(forbidden, code, "%s: %s" % (path, forbidden))

    def test_helper_only_adds_and_demotes(self):
        with open(os.path.join(ROOT, "files/smtp.pl"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("->delete", source)
        self.assertIn("is_default => 0", source)


if __name__ == "__main__":
    unittest.main()
