# SPDX-License-Identifier: MIT-0
import importlib.util
import os
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
SPEC = importlib.util.spec_from_file_location("koha_instance", os.path.join(ROOT, "plugins/module_utils/koha_instance.py"))
ki = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ki)


def params(**overrides):
    p = {"name": "biblioteca", "state": "present", "db_mode": "create", "enable_sru": False}
    p.update(overrides)
    return p


class KohaInstanceHelpersTest(unittest.TestCase):
    def test_name_validation(self):
        ki.validate_params(params())
        for name in ("Biblioteca", "1biblioteca", "biblioteca larga", "biblioteca123"):
            with self.subTest(name=name), self.assertRaises(ki.ModuleInputError):
                ki.validate_params(params(name=name))

    def test_db_mode_and_semantics(self):
        with self.assertRaises(ki.ModuleInputError):
            ki.validate_params(params(db_mode="erase"))
        ki.validate_params(params(db_mode="populate"))
        with self.assertRaises(ki.ModuleInputError):
            ki.validate_params(params(db_mode="use"))
        ki.validate_params(params(db_mode="use", database="koha_biblioteca", db_credentials={"username": "u", "password": "p"}))

    def test_option_validation(self):
        for invalid in ({"marcflavor": "none"}, {"zebralang": "xx"}, {"sru_port": 65536}):
            with self.subTest(invalid=invalid), self.assertRaises(ki.ModuleInputError):
                ki.validate_params(params(**invalid))

    def test_omitted_optional_groups_may_be_none(self):
        ki.validate_params(params(message_broker=None, vhosts=None, db_credentials=None))

    def test_credentials_conflict_and_mode(self):
        with self.assertRaises(ki.ModuleInputError):
            ki.validate_params(params(db_credentials={"username": "u", "password": "p"}, passwdfile="/tmp/passwd"))
        with self.assertRaises(ki.ModuleInputError):
            ki.validate_params(params(db_mode="request", defaultsql="/tmp/default.sql"))

    def test_destructive_actions_require_explicit_confirmations(self):
        with self.assertRaises(ki.ModuleInputError):
            ki.validate_params(params(reconfigure=True))
        ki.validate_params(params(state="absent", remove_database=True))  # state machine checks confirmations before invoking koha-remove
        ki.validate_params(params(state="absent"))
        ki.validate_params(params(reconfigure=True, confirm_name="biblioteca", confirm_data_loss=True))
        ki.validate_params(params(repair=True, confirm_name="biblioteca", confirm_data_loss=True))

    def test_letsencrypt_tls_boundary(self):
        with self.assertRaises(ki.ModuleInputError):
            ki.validate_params(params(letsencrypt=True, tls_termination="proxy"))
        ki.validate_params(params(letsencrypt=True, tls_termination="local"))

    def test_config_quotes_values_and_rejects_newlines(self):
        rendered = ki.render_config(params(vhosts={"domain": ".example.org", "opac_prefix": "x"}))
        self.assertNotIn("CLO_SMTP_", rendered)
        with self.assertRaises(ki.ModuleInputError):
            ki.validate_params(params(vhosts={"domain": ".example.org", "opac_prefix": "$(touch pwned)"}))
        with self.assertRaises(ki.ModuleInputError):
            ki.shell_assignment("DOMAIN", "example\n$(id)")

    def test_repeated_cookies_and_cli_limit(self):
        rendered = ki.render_config(params(keep_cookies=["a", "b-cookie"]))
        self.assertIn("KEEP_COOKIE=(a b-cookie)", rendered)
        argv = ki.build_argv("/usr/sbin/koha-create", "create", "/tmp/config", "biblioteca")
        self.assertEqual(len(argv), 5)
        with self.assertRaises(KeyError):
            ki.build_argv("koha-create", "bad", "/tmp/config", "biblioteca")

    def test_state_classification(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Use patched path checks by creating root-compatible paths is not safe; assert no resources => absent.
            state, paths, marker = ki.inspect_state("koha-test-never-created", os.path.join(tmp, "marker"), os.path.join(tmp, "request"))
            self.assertEqual(state, "absent")
            self.assertFalse(any(paths.values()))
            self.assertEqual(marker, {})


if __name__ == "__main__":
    unittest.main()
