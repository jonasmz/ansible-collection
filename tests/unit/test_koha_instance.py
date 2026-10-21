# SPDX-License-Identifier: MIT-0
import importlib.util
import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
SPEC = importlib.util.spec_from_file_location("koha_instance", os.path.join(ROOT, "plugins/module_utils/koha_instance.py"))
ki = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ki)


def params(**overrides):
    p = {"instance": "biblioteca", "state": "present", "db_mode": "create", "enable_sru": False}
    p.update(overrides)
    return p


class KohaInstanceHelpersTest(unittest.TestCase):
    def test_name_validation(self):
        ki.validate_params(params())
        for name in ("Biblioteca", "1biblioteca", "biblioteca larga", "biblioteca123"):
            with self.subTest(name=name), self.assertRaises(ki.ModuleInputError):
                ki.validate_params(params(instance=name))

    def test_db_mode_and_semantics(self):
        ki.validate_params(params(db_mode="populate"))
        with self.assertRaises(ki.ModuleInputError):
            ki.validate_params(params(db_mode="use"))
        ki.validate_params(params(db_mode="use", database="koha_biblioteca", db_credentials={"username": "u", "password": "p"}))

    def test_option_validation(self):
        for invalid in ({"sru_port": 65536}, {"keep_cookies": ["bad cookie"]}, {"message_broker": {"port": 0}}):
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
        ki.validate_params(params(reconfigure=True, confirm_instance="biblioteca", confirm_data_loss=True))
        ki.validate_params(params(repair=True, confirm_instance="biblioteca", confirm_data_loss=True))

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

    def test_vhost_defaults_ignore_none_values_from_ansible_dict(self):
        rendered = ki.render_config(params(vhosts={
            "domain": ".example.org", "opac_port": None, "opac_prefix": None,
            "opac_suffix": None, "staff_port": None, "staff_prefix": None,
            "staff_suffix": "-staff",
        }))
        self.assertIn("OPACPORT=80\n", rendered)
        self.assertIn("INTRAPORT=80\n", rendered)
        self.assertIn("INTRASUFFIX=-staff\n", rendered)
        self.assertNotIn("None", rendered)

    def test_repeated_cookies_and_cli_limit(self):
        rendered = ki.render_config(params(keep_cookies=["a", "b-cookie"]))
        self.assertIn("KEEP_COOKIE=(a b-cookie)", rendered)
        argv = ki.build_argv("/usr/sbin/koha-create", "create", "/tmp/config", "biblioteca")
        self.assertEqual(len(argv), 5)
        with self.assertRaises(KeyError):
            ki.build_argv("koha-create", "bad", "/tmp/config", "biblioteca")

    def test_db_credentials_are_validated_once_here(self):
        for bad in ({"username": "bad-user", "password": "Valid.Pass-1"}, {"username": "ok", "password": "bad:pass"},
                    {"username": "ok", "password": "bad pass"}):
            with self.subTest(bad=bad), self.assertRaisesRegex(ki.ModuleInputError, "db_credentials"):
                ki.validate_params(params(db_mode="use", database="koha_x", db_credentials=bad))

    def test_vhosts_are_validated(self):
        for bad in ({"opac_port": 80}, {"domain": ".example.org", "staff_port": 70000},
                    {"domain": ".example.org", "staff_suffix": "bad_suffix"}):
            with self.subTest(bad=bad), self.assertRaisesRegex(ki.ModuleInputError, "vhosts"):
                ki.validate_params(params(vhosts=bad))

    def test_adopt_rules(self):
        ki.validate_params(params(adopt=True))
        ki.validate_params(params(adopt=True, db_mode="use", database="koha_x"))
        for bad in (dict(adopt=True, state="absent"), dict(adopt=True, db_mode="request"),
                    dict(adopt=True, db_mode="populate"),
                    dict(adopt=True, repair=True, confirm_instance="biblioteca", confirm_data_loss=True)):
            with self.subTest(bad=bad), self.assertRaises(ki.ModuleInputError):
                ki.validate_params(params(**bad))


if __name__ == "__main__":
    unittest.main()
