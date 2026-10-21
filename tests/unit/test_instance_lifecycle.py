# SPDX-License-Identifier: MIT-0
import contextlib
import importlib.util
import os
import stat
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
PACKAGE = "ansible_collections.jmz.koha.plugins.module_utils"
COMPLETE = {"config": True, "apache": True, "site_dir": True, "user": True, "group": True}


class ModuleExit(Exception):
    def __init__(self, result):
        self.result = result


class FakeAnsibleModule:
    params = {}
    check_mode = False
    results = []
    last = None

    def __init__(self, **kwargs):
        self.params = dict(type(self).params)
        self.check_mode = type(self).check_mode
        self.commands = []
        type(self).last = self

    def get_bin_path(self, name, required=False, opt_dirs=None):
        return "/usr/sbin/" + name

    def run_command(self, argv, **kwargs):
        self.commands.append((argv, kwargs))
        queue = type(self).results
        return queue.pop(0) if queue else (0, "", "")

    def exit_json(self, **kwargs):
        raise ModuleExit(kwargs)

    def fail_json(self, **kwargs):
        raise ModuleExit(dict(kwargs, failed=True))


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_modules():
    names = ["ansible", "ansible.module_utils", "ansible.module_utils.basic", "ansible_collections",
             "ansible_collections.jmz", "ansible_collections.jmz.koha", "ansible_collections.jmz.koha.plugins", PACKAGE]
    fakes = {name: types.ModuleType(name) for name in names}
    fakes["ansible.module_utils.basic"].AnsibleModule = FakeAnsibleModule
    with mock.patch.dict(sys.modules, fakes):
        loaded = {name: _load("plugins/module_utils/%s.py" % name, "%s.%s" % (PACKAGE, name))
                  for name in ("koha_instance", "koha_lock", "koha_instance_state", "koha_instance_backend")}
        loaded["instance"] = _load("plugins/modules/instance.py", "instance_module_test")
    return loaded


def params(**overrides):
    p = {"instance": "biblioteca", "state": "present", "db_mode": "create", "enable_sru": False, "letsencrypt": False,
         "adopt": False, "repair": False, "reconfigure": False, "remove_database": False, "purge_data": False,
         "confirm_data_loss": False}
    p.update(overrides)
    return p


class Base(unittest.TestCase):
    def setUp(self):
        loaded = load_modules()
        self.ki = loaded["koha_instance"]
        self.state = loaded["koha_instance_state"]
        self.lock = loaded["koha_lock"]
        self.backend = loaded["koha_instance_backend"]
        self.module = loaded["instance"]
        FakeAnsibleModule.results = []
        FakeAnsibleModule.check_mode = False


class PlannerTest(Base):
    def plan(self, detected, marker=None, **overrides):
        return self.module.plan_action(params(**overrides), detected, marker or {})

    def confirm(self, **extra):
        return dict(confirm_instance="biblioteca", confirm_data_loss=True, **extra)

    def test_absent_instance_follows_db_mode(self):
        for mode in ("create", "request", "use"):
            self.assertEqual(self.plan("absent", db_mode=mode), mode)

    def test_populate_requires_requested_stage(self):
        self.assertEqual(self.plan("requested", db_mode="populate"), "populate")
        with self.assertRaisesRegex(self.ki.ModuleInputError, "requested"):
            self.plan("absent", db_mode="populate")
        with self.assertRaisesRegex(self.ki.ModuleInputError, "populate"):
            self.plan("requested")

    def test_present_is_noop_unless_configuration_drifts(self):
        marker = {"fingerprint": self.state.fingerprint(params(marcflavor="marc21"))}
        self.assertEqual(self.plan("present", marker, marcflavor="marc21"), "noop")
        with self.assertRaisesRegex(self.ki.ModuleInputError, "drift"):
            self.plan("present", marker, marcflavor="unimarc")
        self.assertEqual(self.plan("present", marker, marcflavor="unimarc", reconfigure=True, **self.confirm()), "rebuild")

    def test_repair_is_not_for_present_instances(self):
        with self.assertRaisesRegex(self.ki.ModuleInputError, "reconfigure"):
            self.plan("present", {"fingerprint": "x"}, repair=True, **self.confirm())

    def test_unmanaged_instance_points_to_adopt_and_never_rebuilds_implicitly(self):
        with self.assertRaisesRegex(self.ki.ModuleInputError, "adopt=true"):
            self.plan("unmanaged")
        self.assertEqual(self.plan("unmanaged", adopt=True), "adopt")
        self.assertEqual(self.plan("unmanaged", repair=True, **self.confirm()), "rebuild")

    def test_adopt_is_idempotent_and_refuses_other_states(self):
        self.assertEqual(self.plan("present", adopt=True), "noop")
        for detected in ("absent", "partial", "requested"):
            with self.subTest(detected=detected), self.assertRaisesRegex(self.ki.ModuleInputError, "adopt"):
                self.plan(detected, adopt=True)

    def test_partial_needs_repair(self):
        with self.assertRaisesRegex(self.ki.ModuleInputError, "repair=true"):
            self.plan("partial")
        self.assertEqual(self.plan("partial", repair=True, **self.confirm()), "rebuild")

    def test_repair_and_reconfigure_need_an_existing_instance(self):
        with self.assertRaisesRegex(self.ki.ModuleInputError, "repair requiere"):
            self.plan("absent", repair=True, **self.confirm())

    def test_absent_state(self):
        self.assertEqual(self.plan("absent", state="absent"), "noop")
        self.assertEqual(self.plan("present", state="absent", **self.confirm()), "remove")
        with self.assertRaisesRegex(self.ki.ModuleInputError, "confirm_instance=instance"):
            self.plan("present", state="absent", confirm_instance="other", confirm_data_loss=True)
        with self.assertRaisesRegex(self.ki.ModuleInputError, "confirm_data_loss"):
            self.plan("present", state="absent", confirm_instance="biblioteca")


class StateTest(Base):
    def test_fingerprint_ignores_operation_inputs_and_secrets(self):
        base = self.state.fingerprint(params(marcflavor="marc21", message_broker={"host": "mq", "password": "a"}))
        for change in ({"db_mode": "use"}, {"koha_create_path": "/opt/koha-create"}, {"db_request_path": "/x"},
                       {"db_credentials": {"username": "u", "password": "p"}}, {"passwdfile": "/p"},
                       {"message_broker": {"host": "mq", "password": "b"}}):
            with self.subTest(change=change):
                self.assertEqual(self.state.fingerprint(params(marcflavor="marc21", **dict({"message_broker": {"host": "mq", "password": "a"}}, **change))), base)

    def test_fingerprint_changes_with_configuration(self):
        base = self.state.fingerprint(params())
        for change in ({"timezone": "UTC"}, {"vhosts": {"domain": ".example.org", "opac_port": None}},
                       {"keep_cookies": ["a"]}, {"message_broker": {"host": "mq"}}):
            with self.subTest(change=change):
                self.assertNotEqual(self.state.fingerprint(params(**change)), base)

    def test_marker_round_trip_is_private_and_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".marker")
            self.state.write_marker(path, "present", "abc")
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            marker = self.state.read_marker(path)
            self.assertEqual((marker["state"], marker["fingerprint"]), ("present", "abc"))
            self.assertEqual(os.listdir(tmp), [".marker"])
            self.state.remove_marker(path)
            self.state.remove_marker(path)
            self.assertEqual(self.state.read_marker(path), {})

    def test_second_run_cannot_take_the_instance_lock(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(self.lock, "LOCK_DIR", tmp):
            with self.state.instance_lock("biblioteca"):
                with self.assertRaisesRegex(self.ki.ModuleInputError, "otra ejecución"):
                    with self.state.instance_lock("biblioteca"):
                        pass
            with self.state.instance_lock("biblioteca"):
                pass

    def test_marker_from_another_schema_or_garbage_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".marker")
            for content in ('{"state": "present", "fingerprint": "x"}', "present", '{"schema_version": 2, "state": "weird"}'):
                with open(path, "w") as stream:
                    stream.write(content)
                with self.subTest(content=content):
                    self.assertEqual(self.state.read_marker(path), {})

    def inspect(self, resources, marker, request_exists=True):
        with mock.patch.object(self.state, "read_marker", return_value=marker), \
             mock.patch.object(self.state.os.path, "exists", side_effect=lambda p: resources.get(self._key(p), False)), \
             mock.patch.object(self.state.os.path, "lexists", return_value=False), \
             mock.patch.object(self.state.os.path, "isfile", return_value=request_exists), \
             mock.patch.object(self.state.pwd, "getpwnam", side_effect=lambda n: None if resources.get("user") else self._missing()), \
             mock.patch.object(self.state.grp, "getgrnam", side_effect=lambda n: None if resources.get("group") else self._missing()):
            return self.state.inspect_state("biblioteca", "/m", "/r")[0]

    @staticmethod
    def _missing():
        raise KeyError("missing")

    @staticmethod
    def _key(path):
        return {"/etc/koha/sites/biblioteca/koha-conf.xml": "config", "/etc/apache2/sites-available/biblioteca.conf": "apache",
                "/var/lib/koha/biblioteca": "site_dir"}.get(path)

    def test_state_classification(self):
        self.assertEqual(self.inspect({}, {}), "absent")
        self.assertEqual(self.inspect(COMPLETE, {}), "unmanaged")
        self.assertEqual(self.inspect(COMPLETE, {"state": "present"}), "present")
        self.assertEqual(self.inspect(COMPLETE, {"state": "requested"}), "requested")
        self.assertEqual(self.inspect(COMPLETE, {"state": "requested"}, request_exists=False), "partial")
        self.assertEqual(self.inspect({"config": True}, {"state": "present"}), "partial")


class PasswdfileTest(Base):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = self.module.Context(params())
        self.existing = "biblioteca:koha_biblioteca:Valid.Password-1:koha_biblioteca:localhost\n"

    def prepare(self, rebuild, config_exists=True, supplied=None, **overrides):
        with mock.patch.object(self.module.os.path, "isfile", return_value=config_exists), \
             mock.patch.object(self.module, "existing_db_credentials", return_value=self.existing), \
             mock.patch.object(self.module, "read_passwd_record", return_value=supplied):
            return self.module._prepare_passwdfile(params(**overrides), self.ctx, self.tmp.name, rebuild)

    def read(self, path):
        with open(path, encoding="utf-8") as stream:
            return stream.read()

    def test_new_instance_without_credentials_needs_no_passwdfile(self):
        self.assertIsNone(self.prepare(False))

    def test_credentials_become_a_private_passwdfile_with_conventional_defaults(self):
        path = self.prepare(False, db_credentials={"username": "koha_biblioteca", "password": "Valid.Password-1"})
        self.assertEqual(self.read(path), self.existing)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_rebuild_reuses_the_record_found_in_koha_conf(self):
        self.assertEqual(self.read(self.prepare(True)), self.existing)

    def test_rebuild_rejects_a_different_database_or_host(self):
        for overrides in ({"database": "otra"}, {"dbhost": "db.example.org"}):
            with self.subTest(overrides=overrides), self.assertRaisesRegex(self.ki.ModuleInputError, "no cambia|no migra"):
                self.prepare(True, **overrides)

    def test_rebuild_with_passwdfile_must_point_to_the_same_database(self):
        same = ["biblioteca", "u", "p", "koha_biblioteca", "localhost"]
        self.assertEqual(self.prepare(True, supplied=same, passwdfile="/etc/pw"), "/etc/pw")
        with self.assertRaisesRegex(self.ki.ModuleInputError, "DB/host distintos"):
            self.prepare(True, supplied=["biblioteca", "u", "p", "otra", "localhost"], passwdfile="/etc/pw")

    def test_rebuild_without_config_needs_explicit_credentials(self):
        with self.assertRaisesRegex(self.ki.ModuleInputError, "db_credentials o passwdfile"):
            self.prepare(True, config_exists=False)
        with self.assertRaisesRegex(self.ki.ModuleInputError, "requiere database"):
            self.prepare(True, config_exists=False, db_credentials={"username": "u", "password": "p"})
        path = self.prepare(True, config_exists=False, database="koha_x", db_credentials={"username": "u", "password": "p"})
        self.assertEqual(self.read(path), "biblioteca:u:p:koha_x:localhost\n")


class HelpersTest(Base):
    def test_apache_prerequisites_report_missing_module_actionably(self):
        fake = mock.Mock()
        fake.get_bin_path.return_value = "/usr/sbin/apachectl"
        fake.run_command.return_value = (0, " mpm_itk_module (shared)\n", "")
        with self.assertRaisesRegex(self.ki.ModuleInputError, "a2enmod rewrite"):
            self.backend.check_apache_prerequisites(fake)
        fake.run_command.return_value = (0, " mpm_itk_module (shared)\n rewrite_module (shared)\n", "")
        with self.assertRaisesRegex(self.ki.ModuleInputError, "a2enmod cgi"):
            self.backend.check_apache_prerequisites(fake)

    def test_backend_failure_hint_never_echoes_diagnostics(self):
        output = "ERROR 1045: Access denied for user 'koha_test' using password: super-secret"
        hint = self.backend.failure_hint(output)
        self.assertIn("autenticación", hint)
        self.assertNotIn("super-secret", hint)

    def test_vhost_hostnames_treat_omitted_fields_as_empty(self):
        self.assertEqual(self.backend.vhost_hostnames("koha", {"domain": ".example.org", "staff_suffix": "-staff"}),
                         ("koha.example.org", "koha-staff.example.org"))

    def test_restore_brings_back_only_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup, sites = os.path.join(tmp, "backup"), os.path.join(tmp, "sites")
            os.makedirs(os.path.join(backup, "sites", "sub"))
            os.makedirs(os.path.join(sites, "biblioteca"))
            for relative, content in (("koha-conf.xml", "old"), ("zebra.passwd", "old"), ("sub/extra", "old")):
                with open(os.path.join(backup, "sites", relative), "w") as stream:
                    stream.write(content)
            with open(os.path.join(sites, "biblioteca", "zebra.passwd"), "w") as stream:
                stream.write("new")
            self.assertTrue(self.backend.restore_site_config("biblioteca", backup, sites))
            def read(relative):
                with open(os.path.join(sites, "biblioteca", relative)) as stream:
                    return stream.read()

            self.assertEqual((read("koha-conf.xml"), read("zebra.passwd"), read("sub/extra")), ("old", "new", "old"))

    def test_restore_reports_when_koha_conf_is_still_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "backup", "sites"))
            self.assertFalse(self.backend.restore_site_config("biblioteca", os.path.join(tmp, "backup"), os.path.join(tmp, "sites")))

    def test_explicit_binary_must_be_executable(self):
        with self.assertRaisesRegex(self.ki.ModuleInputError, "no es un ejecutable"):
            self.backend.resolve_binary(FakeAnsibleModule(), "/nonexistent/koha-remove", "koha-remove")

    def write_conf(self, xml):
        stream = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8")
        stream.write(xml)
        stream.flush()
        self.addCleanup(stream.close)
        return stream.name

    def test_existing_db_credentials_use_supplied_secret(self):
        path = self.write_conf("""<?xml version="1.0"?>
<yazgfs><listen><server><config><timeout>30</timeout></config></server></listen>
<config><database>koha_biblioteca</database><hostname>localhost</hostname>
<user>old_user</user><pass>legacy/unsafe&amp;secret</pass></config></yazgfs>""")
        record = self.backend.existing_db_credentials(path, "biblioteca", {"username": "koha_biblioteca", "password": "Valid.Password-1"})
        self.assertEqual(record, "biblioteca:koha_biblioteca:Valid.Password-1:koha_biblioteca:localhost\n")

    def test_existing_db_credentials_parse_standard_structure(self):
        path = self.write_conf("""<yazgfs><config><database>koha_biblioteca</database><hostname>db.internal</hostname>
<user>koha_biblioteca</user><pass>Valid.Password-1</pass></config></yazgfs>""")
        self.assertEqual(self.backend.existing_db_credentials(path, "biblioteca"),
                         "biblioteca:koha_biblioteca:Valid.Password-1:koha_biblioteca:db.internal\n")

    def test_corrupt_koha_conf_is_a_controlled_error(self):
        path = self.write_conf("<yazgfs><config>")
        with self.assertRaisesRegex(self.ki.ModuleInputError, "koha-conf.xml"):
            self.backend.existing_db_credentials(path, "biblioteca")

    def test_passwdfile_record_is_validated_without_echoing_secret(self):
        path = self.write_conf("biblioteca:koha_biblioteca:Strong.Pass-1:koha_biblioteca:db.example.org\n")
        self.assertEqual(self.backend.read_passwd_record(path, "biblioteca")[1], "koha_biblioteca")
        path = self.write_conf("biblioteca:koha_biblioteca:bad/secret:koha_biblioteca:localhost\n")
        with self.assertRaises(self.ki.ModuleInputError) as raised:
            self.backend.read_passwd_record(path, "biblioteca")
        self.assertNotIn("bad/secret", str(raised.exception))


class MainTest(Base):
    def run_main(self, detected="present", marker=None, check_mode=False, results=None, inspected=None,
                 site_dir_exists=True, path_exists=False, restore_ok=True, **overrides):
        FakeAnsibleModule.params = params(**overrides)
        FakeAnsibleModule.check_mode = check_mode
        FakeAnsibleModule.results = list(results or [])
        states = inspected or [(detected, dict(COMPLETE), marker or {})]
        patches = {
            "inspect_state": mock.patch.object(self.module, "inspect_state", side_effect=list(states) + [states[-1]] * 3),
            "geteuid": mock.patch.object(self.module.os, "geteuid", return_value=0),
            "lock": mock.patch.object(self.module, "instance_lock", side_effect=lambda name: contextlib.nullcontext()),
            "write_marker": mock.patch.object(self.module, "write_marker"),
            "remove_marker": mock.patch.object(self.module, "remove_marker"),
            "isdir": mock.patch.object(self.module.os.path, "isdir", return_value=site_dir_exists),
            "exists": mock.patch.object(self.module.os.path, "exists", return_value=path_exists),
            "isfile": mock.patch.object(self.module.os.path, "isfile", return_value=True),
            "resolve": mock.patch.object(self.module, "resolve_binary", side_effect=lambda m, e, n: "/usr/sbin/" + n),
            "apache": mock.patch.object(self.module, "check_apache_prerequisites"),
            "options": mock.patch.object(self.module, "require_options"),
            "passwd": mock.patch.object(self.module, "_prepare_passwdfile", return_value="/tmp/passwd"),
            "backup": mock.patch.object(self.module, "backup_instance", return_value="/var/backups/ansible-koha-biblioteca-x"),
            "rmtree": mock.patch.object(self.module.shutil, "rmtree"),
            "write_private": mock.patch.object(self.module, "write_private"),
            "restore": mock.patch.object(self.module, "restore_site_config", return_value=restore_ok),
            "mkdir": mock.patch.object(self.module.os, "mkdir"),
            "replace": mock.patch.object(self.module.os, "replace"),
            "chmod": mock.patch.object(self.module.os, "chmod"),
        }
        started = {name: patch.start() for name, patch in patches.items()}
        for patch in patches.values():
            self.addCleanup(patch.stop)
        with self.assertRaises(ModuleExit) as raised:
            self.module.main()
        self.mocks = started
        return raised.exception.result, FakeAnsibleModule.last.commands

    def remove_params(self, **extra):
        return dict(state="absent", confirm_instance="biblioteca", confirm_data_loss=True, **extra)

    def test_noop_does_not_touch_the_host(self):
        marker = {"fingerprint": self.state.fingerprint(params())}
        result, commands = self.run_main(marker=marker)
        self.assertFalse(result["changed"])
        self.assertEqual(commands, [])
        self.assertEqual(result["state"], "present")
        self.assertNotIn("name", result)
        self.mocks["write_marker"].assert_not_called()

    def test_adopt_writes_marker_without_running_koha(self):
        result, commands = self.run_main(detected="unmanaged", adopt=True, marcflavor="marc21")
        self.assertTrue(result["changed"])
        self.assertEqual(commands, [])
        args = self.mocks["write_marker"].call_args.args
        self.assertEqual(args[1:], ("present", self.state.fingerprint(params(marcflavor="marc21"))))

    def test_adopt_check_mode_writes_nothing(self):
        result, _ = self.run_main(detected="unmanaged", adopt=True, check_mode=True)
        self.assertTrue(result["changed"])
        self.assertEqual(result["actions"], ["registrar marcador de instancia"])
        self.mocks["write_marker"].assert_not_called()

    def test_unmanaged_without_adopt_fails_with_guidance(self):
        result, commands = self.run_main(detected="unmanaged")
        self.assertIn("adopt=true", result["msg"])
        self.assertEqual(commands, [])

    def test_create_runs_koha_create_and_records_marker(self):
        result, commands = self.run_main(detected="absent", inspected=[("absent", {}, {}), ("present", dict(COMPLETE), {})])
        self.assertTrue(result["changed"])
        self.assertEqual(result["actions"], ["koha-create --create"])
        self.assertEqual(commands[0][0][:2], ["/usr/sbin/koha-create", "--create-db"])
        self.assertEqual(self.mocks["write_marker"].call_args.args[1], "present")

    def test_create_reports_missing_resources_as_partial(self):
        result, _ = self.run_main(detected="absent", inspected=[("absent", {}, {}), ("partial", {"config": True}, {})])
        self.assertIn("faltan recursos", result["msg"])
        self.assertTrue(result["partial"])
        self.mocks["write_marker"].assert_not_called()

    def test_create_failure_never_echoes_backend_output(self):
        result, _ = self.run_main(detected="absent", results=[(1, "", "ERROR 1045 Access denied password: s3cret")])
        self.assertIn("autenticación", result["msg"])
        self.assertNotIn("s3cret", str(result))
        self.assertFalse(result["partial"])

    def rebuild_params(self):
        return dict(reconfigure=True, confirm_instance="biblioteca", confirm_data_loss=True, marcflavor="marc21")

    def test_rebuild_check_mode_plans_database_preserving_rebuild(self):
        marker = {"fingerprint": "old"}
        result, commands = self.run_main(marker=marker, check_mode=True, **self.rebuild_params())
        self.assertTrue(result["changed"])
        self.assertEqual(result["actions"], ["koha-remove --keep-mysql", "koha-create --use-db"])
        self.assertEqual(commands, [])

    def test_partial_repair_check_mode_plans_rebuild(self):
        result, _ = self.run_main(detected="partial", check_mode=True, repair=True, confirm_instance="biblioteca", confirm_data_loss=True)
        self.assertEqual(result["actions"], ["koha-remove --keep-mysql", "koha-create --use-db"])

    def test_rebuild_success_removes_the_backup(self):
        result, commands = self.run_main(marker={"fingerprint": "old"}, **self.rebuild_params())
        self.assertEqual(result["actions"], ["koha-remove --keep-mysql", "koha-create --use-db"])
        self.assertEqual(commands[0][0], ["/usr/sbin/koha-remove", "--keep-mysql", "biblioteca"])
        self.assertEqual(commands[1][0][:2], ["/usr/sbin/koha-create", "--use-db"])
        self.assertIn(mock.call("/var/backups/ansible-koha-biblioteca-x", ignore_errors=True), self.mocks["rmtree"].call_args_list)

    def test_rebuild_failure_after_remove_is_reported_and_keeps_the_backup(self):
        result, _ = self.run_main(marker={"fingerprint": "old"}, results=[(0, "", ""), (1, "", "boom")], **self.rebuild_params())
        self.assertTrue(result["failed"])
        self.assertTrue(result["changed"] and result["partial"])
        self.assertEqual(result["actions"], ["koha-remove --keep-mysql", "restaurar configuración previa"])
        self.assertIn("se restauró", result["msg"])
        self.assertIn("/var/backups/ansible-koha-biblioteca-x", result["msg"])
        self.mocks["restore"].assert_called_once_with("biblioteca", "/var/backups/ansible-koha-biblioteca-x")
        self.assertNotIn(mock.call("/var/backups/ansible-koha-biblioteca-x", ignore_errors=True), self.mocks["rmtree"].call_args_list)

    def test_rebuild_failure_without_restorable_config_says_so(self):
        result, _ = self.run_main(marker={"fingerprint": "old"}, results=[(0, "", ""), (1, "", "boom")],
                                  restore_ok=False, **self.rebuild_params())
        self.assertIn("sin configuración", result["msg"])

    def test_request_stage_moves_the_generated_file_and_records_it(self):
        request = "/var/lib/koha/biblioteca/biblioteca-db-request.txt"
        result, commands = self.run_main(detected="absent", db_mode="request",
                                         inspected=[("absent", {}, {}), ("requested", dict(COMPLETE), {})])
        self.assertEqual(result["state"], "requested")
        self.assertEqual(result["request_file"], request)
        self.assertEqual(result["actions"], ["koha-create --request"])
        self.assertEqual(commands[0][0][:2], ["/usr/sbin/koha-create", "--request-db"])
        source, target = self.mocks["replace"].call_args.args
        self.assertTrue(source.endswith("/biblioteca-db-request.txt"))
        self.assertEqual(target, request)
        self.assertEqual(self.mocks["write_marker"].call_args.args[1], "requested")
        self.assertEqual(self.mocks["write_marker"].call_args.args[3], request)

    def test_request_stage_never_overwrites_an_existing_request(self):
        result, commands = self.run_main(detected="absent", db_mode="request", path_exists=True)
        self.assertIn("db_request_path ya existe", result["msg"])
        self.assertEqual(commands, [])

    def test_populate_stage_uses_the_request_recorded_in_the_marker(self):
        marker = {"state": "requested", "request_file": "/custom/req.txt"}
        result, commands = self.run_main(db_mode="populate", inspected=[
            ("partial", dict(COMPLETE), marker), ("requested", dict(COMPLETE), marker), ("present", dict(COMPLETE), {})])
        self.assertEqual(result["actions"], ["koha-create --populate"])
        self.assertEqual(result["state"], "present")
        self.assertEqual(commands[0][0][:2], ["/usr/sbin/koha-create", "--populate-db"])
        self.assertEqual(self.mocks["inspect_state"].call_args_list[1].args[2], "/custom/req.txt")
        self.assertEqual(self.mocks["write_marker"].call_args.args[1], "present")
        self.assertIsNone(self.mocks["write_marker"].call_args.args[3])

    def test_absent_recreates_the_missing_site_directory_so_koha_remove_can_clean_up(self):
        result, commands = self.run_main(detected="partial", site_dir_exists=False, **self.remove_params())
        self.mocks["mkdir"].assert_called_once_with("/etc/koha/sites/biblioteca", 0o755)
        self.assertEqual(result["actions"], ["crear directorio de sitio vacío para koha-remove", "koha-remove"])
        self.assertEqual(commands[0][0][0], "/usr/sbin/koha-remove")

    def test_absent_check_mode_does_not_create_the_site_directory(self):
        self.run_main(detected="partial", site_dir_exists=False, check_mode=True, **self.remove_params())
        self.mocks["mkdir"].assert_not_called()

    def test_absent_preserves_database_by_default(self):
        result, commands = self.run_main(**self.remove_params())
        self.assertTrue(result["changed"])
        self.assertEqual(commands[0][0], ["/usr/sbin/koha-remove", "--keep-mysql", "biblioteca"])

    def test_absent_explicitly_purges_database_and_data(self):
        _, commands = self.run_main(**self.remove_params(remove_database=True, purge_data=True))
        self.assertEqual(commands[0][0], ["/usr/sbin/koha-remove", "--purge-all", "biblioteca"])

    def test_absent_check_mode_does_not_call_backend(self):
        result, commands = self.run_main(check_mode=True, **self.remove_params())
        self.assertTrue(result["changed"])
        self.assertEqual(commands, [])

    def test_absent_needs_both_confirmations(self):
        result, commands = self.run_main(state="absent", confirm_instance="other", confirm_data_loss=True)
        self.assertIn("confirm_instance=instance", result["msg"])
        self.assertEqual(commands, [])

    def test_absent_on_absent_instance_is_noop(self):
        result, _ = self.run_main(detected="absent", state="absent")
        self.assertFalse(result["changed"])
        self.assertEqual(result["state"], "absent")

    def test_requires_root_for_mutations(self):
        FakeAnsibleModule.params = params()
        with mock.patch.object(self.module, "inspect_state", return_value=("absent", {}, {})), \
             mock.patch.object(self.module.os.path, "exists", return_value=False), \
             mock.patch.object(self.module.os, "geteuid", return_value=1000):
            with self.assertRaises(ModuleExit) as raised:
                self.module.main()
        self.assertIn("become", raised.exception.result["msg"])

    def test_check_mode_needs_neither_root_nor_binaries(self):
        FakeAnsibleModule.params = params()
        FakeAnsibleModule.check_mode = True
        with mock.patch.object(self.module, "inspect_state", return_value=("absent", {}, {})), \
             mock.patch.object(self.module.os.path, "exists", return_value=False), \
             mock.patch.object(self.module.os, "geteuid", return_value=1000):
            with self.assertRaises(ModuleExit) as raised:
                self.module.main()
        self.assertTrue(raised.exception.result["changed"])


if __name__ == "__main__":
    unittest.main()
