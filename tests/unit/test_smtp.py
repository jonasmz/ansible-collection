# SPDX-License-Identifier: MIT-0
import importlib.util
import os
import sys
import tempfile
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
    last = None

    def __init__(self, **kwargs):
        self.params = dict(type(self).params)
        self.check_mode = type(self).check_mode
        self._diff = True
        type(self).last = self

    def exit_json(self, **kwargs):
        raise ModuleExit(kwargs)

    def fail_json(self, **kwargs):
        raise ModuleExit(kwargs)

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


class SmtpModuleTest(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.raw = (b'<?xml version="1.0"?>\n<yazgfs><config>\n'
                    b'  <!-- preserve this -->\n  <smtp_server>\n'
                    b'    <host>old.example.org</host>\n    <port>25</port>\n'
                    b'    <timeout>120</timeout>\n    <ssl_mode>disabled</ssl_mode>\n'
                    b'    <user_name></user_name>\n    <password></password>\n'
                    b'    <debug>0</debug>\n  </smtp_server>\n'
                    b'  <unrelated>keep &amp; intact</unrelated>\n</config></yazgfs>')

    def test_instance_validation_rejects_traversal_and_injection(self):
        for instance in ("../other", "library;touch /tmp/pwned", "A", "a" * 12):
            with self.subTest(instance=instance), self.assertRaises(self.module.SmtpError):
                self.module._validate({"instance": instance})

    def test_parameter_validation_and_empty_password_clear(self):
        with self.assertRaisesRegex(self.module.SmtpError, "port"):
            self.module._validate({"instance": "biblioteca", "server": {"port": 65536}})
        with self.assertRaisesRegex(self.module.SmtpError, "hostname"):
            self.module._validate({"instance": "biblioteca", "server": {"host": "smtp.example;id"}})
        with self.assertRaisesRegex(self.module.SmtpError, "ssl_mode"):
            self.module._validate({"instance": "biblioteca", "server": {"ssl_mode": "tls"}})
        with self.assertRaisesRegex(self.module.SmtpError, "correo"):
            self.module._validate({"instance": "biblioteca", "admin_email_address": "bad"})
        self.module._validate({"instance": "biblioteca", "server": {"password": ""}})

    def test_xml_is_idempotent_and_partial_update_preserves_other_values(self):
        inv = self.module._xml_inventory(self.raw)
        self.assertEqual(self.module._current_values(self.raw, inv)["host"], "old.example.org")
        updated, changed = self.module._updated_xml(self.raw, inv, {"port": 587})
        self.assertTrue(changed)
        self.assertIn(b"<host>old.example.org</host>", updated)
        self.assertIn(b"<port>587</port>", updated)
        self.assertIn(b"<!-- preserve this -->", updated)
        self.assertIn(b"<unrelated>keep &amp; intact</unrelated>", updated)
        repeat, changed = self.module._updated_xml(updated, self.module._xml_inventory(updated), {"port": 587})
        self.assertFalse(changed)
        self.assertEqual(repeat, updated)

    def test_xml_escapes_values_and_clears_password_without_leaking_it(self):
        inv = self.module._xml_inventory(self.raw)
        secret = "p<&>ass"
        updated, changed = self.module._updated_xml(self.raw, inv, {"host": "smtp.example.org", "password": secret})
        self.assertTrue(changed)
        self.assertIn(b"<password>p&lt;&amp;&gt;ass</password>", updated)
        self.assertNotIn(secret.encode(), updated)
        cleared, changed = self.module._updated_xml(updated, self.module._xml_inventory(updated), {"password": ""})
        self.assertTrue(changed)
        self.assertIn(b"<password></password>", cleared)

    def test_existing_xml_entities_compare_by_decoded_value(self):
        encoded = self.raw.replace(b"<user_name></user_name>",
                                   b"<user_name>ops&amp;oncall@example.org</user_name>")
        inventory = self.module._xml_inventory(encoded)
        self.assertEqual(self.module._current_values(encoded, inventory)["user_name"], "ops&oncall@example.org")
        unchanged, changed = self.module._updated_xml(encoded, inventory,
                                                       {"user_name": "ops&oncall@example.org"})
        self.assertFalse(changed)
        self.assertEqual(unchanged, encoded)

    def test_password_whitespace_is_significant_and_idempotent(self):
        encoded = self.raw.replace(b"<password></password>", b"<password> secret </password>")
        inventory = self.module._xml_inventory(encoded)
        same, changed = self.module._updated_xml(encoded, inventory, {"password": " secret "})
        self.assertFalse(changed)
        self.assertEqual(same, encoded)
        updated, changed = self.module._updated_xml(encoded, inventory, {"password": "new secret"})
        self.assertTrue(changed)
        self.assertIn(b"<password>new secret</password>", updated)

    def test_duplicate_smtp_elements_are_rejected(self):
        duplicate = self.raw.replace(b"<port>25</port>", b"<port>25</port><port>26</port>")
        with self.assertRaisesRegex(self.module.SmtpError, "duplicados"):
            self.module._xml_inventory(duplicate)

    def test_malformed_xml_and_missing_target_fail_closed(self):
        with self.assertRaises(self.module.xml.parsers.expat.ExpatError):
            self.module._xml_inventory(b"<broken>")
        no_smtp = b"<yazgfs><config/></yazgfs>"
        with self.assertRaisesRegex(self.module.SmtpError, "Falta"):
            self.module._updated_xml(no_smtp, self.module._xml_inventory(no_smtp), {"host": "smtp.example.org"})

    def test_atomic_replace_preserves_owner_group_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "koha-conf.xml")
            with open(path, "wb") as stream:
                stream.write(b"original")
            original = os.stat(path)
            fake_stat = types.SimpleNamespace(st_mode=0o100640, st_dev=original.st_dev, st_ino=original.st_ino)
            original_meta = types.SimpleNamespace(st_uid=123, st_gid=456, st_mode=0o100640,
                                                  st_dev=original.st_dev, st_ino=original.st_ino)
            with mock.patch.object(self.module.os, "fchown") as chown, \
                    mock.patch.object(self.module.os, "fchmod") as chmod, \
                    mock.patch.object(self.module.os, "fsync"), \
                    mock.patch.object(self.module.os, "stat", return_value=fake_stat):
                self.module._atomic_replace(path, b"updated",
                                            original_meta)
            with open(path, "rb") as stream:
                self.assertEqual(stream.read(), b"updated")
        chown.assert_called_once_with(mock.ANY, 123, 456)
        chmod.assert_called_once_with(mock.ANY, 0o640)

    def _run_main(self, params, check_mode=False, db_default=False, enabled_initial=False, apply_enabled=True):
        FakeAnsibleModule.params = {"_smtp_probe": "/tmp/smtp_probe.pl", "timeout": 60, **params}
        FakeAnsibleModule.check_mode = check_mode
        conf = "/etc/koha/sites/biblioteca/koha-conf.xml"
        data_dir = "/var/lib/koha/biblioteca"
        enabled_path = data_dir + "/email.enabled"
        enabled_state = {"value": enabled_initial}
        def exists(path):
            return enabled_state["value"] if path == enabled_path else False
        def run(command, data=None, timeout=60):
            if command[0].endswith("koha-email-enable") and apply_enabled:
                enabled_state["value"] = True
            if command[0].endswith("koha-email-disable") and apply_enabled:
                enabled_state["value"] = False
            return 0, "", ""
        with mock.patch.object(self.module.os, "geteuid", return_value=0), \
                mock.patch.object(self.module.pwd, "getpwnam"), \
                mock.patch.object(self.module.os.path, "islink", return_value=False), \
                mock.patch.object(self.module.os.path, "realpath", side_effect=lambda value: value), \
                mock.patch.object(self.module.os.path, "isfile",
                                  side_effect=lambda path: enabled_state["value"] if path == enabled_path else True), \
                mock.patch.object(self.module.os.path, "isdir", return_value=True), \
                mock.patch.object(self.module.os, "access", return_value=True), \
                mock.patch.object(self.module.os.path, "exists", side_effect=exists), \
                mock.patch.object(self.module, "_read_xml", return_value=(self.raw,
                    types.SimpleNamespace(st_uid=0, st_gid=0, st_mode=0o100640, st_dev=1, st_ino=1),
                    self.module._xml_inventory(self.raw))), \
                mock.patch.object(self.module, "_koha_probe", return_value={"needs_install": False,
                    "has_smtp_api": True, "has_context": True, "database_default": db_default,
                    "effective_source": "database" if db_default else "xml"}), \
                mock.patch.object(self.module, "_atomic_replace") as atomic, \
                mock.patch.object(self.module, "_preference", return_value="") as preference, \
                mock.patch.object(self.module, "_run", side_effect=run) as run_mock:
            with self.assertRaises(ModuleExit) as raised:
                self.module.main()
        return raised.exception.result, atomic, preference, run_mock

    def test_check_mode_reports_safe_diff_without_mutation(self):
        result, atomic, _, run = self._run_main({"instance": "biblioteca", "server": {
            "host": "smtp.example.org", "password": "do-not-return"}}, check_mode=True)
        self.assertTrue(result["changed"])
        self.assertTrue(result["smtp_changed"])
        self.assertEqual(result["diff"]["after"]["password"], "<redacted>")
        self.assertNotIn("do-not-return", repr(result))
        atomic.assert_not_called()
        run.assert_not_called()

    def test_database_default_conflict_fails_before_writes(self):
        result, atomic, _, _ = self._run_main({"instance": "biblioteca", "server": {"host": "smtp.example.org"}},
                                              db_default=True)
        self.assertIn("predeterminado persistido", result["msg"])
        atomic.assert_not_called()

    def test_enable_command_is_idempotent_and_postcondition_is_required(self):
        result, atomic, _, run = self._run_main({"instance": "biblioteca", "enabled": True})
        self.assertTrue(result["changed"])
        self.assertTrue(result["email_enabled_changed"])
        self.assertEqual(run.call_args.args[0], ["/usr/sbin/koha-email-enable", "biblioteca"])
        result, _, _, run = self._run_main({"instance": "biblioteca", "enabled": True}, enabled_initial=True)
        self.assertFalse(result["changed"])
        run.assert_not_called()
        result, _, _, _ = self._run_main({"instance": "biblioteca", "enabled": True}, apply_enabled=False)
        self.assertIn("no dejó email.enabled", result["msg"])

    def test_admin_preference_is_compared_and_verified_before_reporting_change(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "admin_email_address": "admin@example.org",
                                    "_smtp_probe": "/tmp/smtp_probe.pl", "timeout": 60}
        FakeAnsibleModule.check_mode = False
        conf = "/etc/koha/sites/biblioteca/koha-conf.xml"
        data_dir = "/var/lib/koha/biblioteca"
        enabled_path = data_dir + "/email.enabled"
        current = {"value": "old@example.org"}
        def preference(module, instance, operation, value=None, timeout=60):
            if operation == "set":
                current["value"] = value
            return current["value"]
        with mock.patch.object(self.module.os, "geteuid", return_value=0), \
                mock.patch.object(self.module.pwd, "getpwnam"), \
                mock.patch.object(self.module.os.path, "islink", return_value=False), \
                mock.patch.object(self.module.os.path, "realpath", side_effect=lambda value: value), \
                mock.patch.object(self.module.os.path, "isfile", return_value=True), \
                mock.patch.object(self.module.os.path, "isdir", return_value=True), \
                mock.patch.object(self.module.os, "access", return_value=True), \
                mock.patch.object(self.module.os.path, "exists", side_effect=lambda value: False), \
                mock.patch.object(self.module, "_read_xml", return_value=(self.raw,
                    types.SimpleNamespace(st_uid=0, st_gid=0, st_mode=0o100640, st_dev=1, st_ino=1),
                    self.module._xml_inventory(self.raw))), \
                mock.patch.object(self.module, "_koha_probe", return_value={"needs_install": False,
                    "has_smtp_api": True, "has_context": True, "database_default": False, "effective_source": "xml"}), \
                mock.patch.object(self.module, "_preference", side_effect=preference):
            with self.assertRaises(ModuleExit) as raised:
                self.module.main()
        self.assertTrue(raised.exception.result["changed"])
        self.assertTrue(raised.exception.result["admin_email_changed"])
        self.assertEqual(current["value"], "admin@example.org")

    def test_preference_write_uses_yaml_stdin_and_fixed_shell_command(self):
        address = "admin+koha@example.org"
        proc = types.SimpleNamespace(returncode=0, communicate=mock.Mock(return_value=(b"", b"")))
        with mock.patch.object(self.module.subprocess, "Popen", return_value=proc) as popen, \
                mock.patch.object(self.module.os.path, "isfile", return_value=True), \
                mock.patch.object(self.module.os, "access", return_value=True):
            self.module._preference(FakeAnsibleModule(), "biblioteca", "set", address)
        argv = popen.call_args.args[0]
        self.assertEqual(argv[-1], "biblioteca")
        self.assertNotIn(address, repr(argv))
        self.assertIn(address, proc.communicate.call_args.args[0].decode())

    def test_database_uninitialized_error_precedes_all_mutations(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "enabled": True,
                                    "_smtp_probe": "/tmp/smtp_probe.pl", "timeout": 60}
        FakeAnsibleModule.check_mode = False
        conf = "/etc/koha/sites/biblioteca/koha-conf.xml"
        data_dir = "/var/lib/koha/biblioteca"
        enabled_path = data_dir + "/email.enabled"
        with mock.patch.object(self.module.os, "geteuid", return_value=0), \
                mock.patch.object(self.module.pwd, "getpwnam"), \
                mock.patch.object(self.module.os.path, "islink", return_value=False), \
                mock.patch.object(self.module.os.path, "realpath", side_effect=lambda value: value), \
                mock.patch.object(self.module.os.path, "isfile", return_value=True), \
                mock.patch.object(self.module.os.path, "isdir", return_value=True), \
                mock.patch.object(self.module.os, "access", return_value=True), \
                mock.patch.object(self.module.os.path, "exists", side_effect=lambda value: value == enabled_path and False), \
                mock.patch.object(self.module, "_read_xml", return_value=(self.raw,
                    types.SimpleNamespace(st_uid=0, st_gid=0, st_mode=0o100640, st_dev=1, st_ino=1),
                    self.module._xml_inventory(self.raw))), \
                mock.patch.object(self.module, "_koha_probe", return_value={"needs_install": True}), \
                mock.patch.object(self.module, "_run") as run, \
                mock.patch.object(self.module, "_atomic_replace") as atomic:
            with self.assertRaises(ModuleExit) as raised:
                self.module.main()
        self.assertIn("Ejecute initialize antes de smtp", raised.exception.result["msg"])
        run.assert_not_called()
        atomic.assert_not_called()


if __name__ == "__main__":
    unittest.main()
