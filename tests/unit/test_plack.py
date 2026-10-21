# SPDX-License-Identifier: MIT-0
"""Unit tests for the Plack module; Koha commands and the Apache site file are simulated."""

import unittest
from unittest import mock

from tests.unit.service_fakes import FakeAnsibleModule, FakeHost, ModuleExit, load_module, patch_host


ENABLED = "Include /etc/koha/apache-shared-opac-plack.conf\nInclude /etc/koha/apache-shared-intranet-plack.conf\n"
DISABLED = "#Include /etc/koha/apache-shared-opac-plack.conf\n#Include /etc/koha/apache-shared-intranet-plack.conf\n"
MODULES = " headers_module (shared)\n proxy_http_module (shared)\n"


class PlackModuleTest(unittest.TestCase):
    def setUp(self):
        FakeAnsibleModule.params = {"instance": "biblioteca"}
        FakeAnsibleModule.check_mode = False
        self.module = load_module("plack")
        self.host = FakeHost()
        self.site = {"content": ENABLED}
        self.apache = {"modules": MODULES}
        FakeAnsibleModule.runner = self.host
        self.host.extra["apache2ctl"] = self.apache_ctl
        self.host.extra["koha-plack"] = self.koha_plack
        patch_host(self, self.module, files={"/etc/apache2/sites-available/biblioteca.conf"})
        patcher = mock.patch.object(self.module.os.path, "isfile", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        opener = mock.patch("builtins.open", lambda *a, **k: mock.mock_open(read_data=self.site["content"])())
        opener.start()
        self.addCleanup(opener.stop)

    def apache_ctl(self, argv):
        self.host.log.append(("apache2ctl", argv[1]))
        return (0, self.apache["modules"], "") if argv[1] == "-M" else (0, "", "")

    def koha_plack(self, argv):
        operation = argv[1]
        if operation in ("--enable", "--disable"):
            self.host.log.append(("koha-plack", operation))
            self.site["content"] = ENABLED if operation == "--enable" else DISABLED
            return 0, "", ""
        key = "koha-plack"
        if operation == "--status":
            if self.host.states[key] == "started":
                return 0, " * Plack running for biblioteca\n", ""
            return 3, " * Plack not running for biblioteca\n", ""
        self.host.log.append((key, operation))
        if operation in ("--start", "--restart"):
            self.host.states[key] = "started"
        elif operation == "--stop":
            self.host.states[key] = "stopped"
        return 0, "", ""

    def run_module(self, **params):
        FakeAnsibleModule.params.update(params)
        with self.assertRaises(ModuleExit) as raised:
            self.module.main()
        return raised.exception.result

    def test_stopped_status_and_stop_report_no_rc(self):
        # Ansible fails a task whose result carries a nonzero rc; koha-plack --status returns 3 when stopped.
        result = self.run_module(state="stopped")
        self.assertNotIn("rc", result)
        self.assertFalse(result["changed"])
        self.assertFalse(result["running"])
        self.assertFalse(self.run_module(state="status").get("failed"))

    def test_start_restart_and_stop_cycle(self):
        self.assertTrue(self.run_module(state="started")["running"])
        self.assertFalse(self.run_module(state="started")["changed"])
        self.assertTrue(self.run_module(state="restarted")["changed"])
        self.assertFalse(self.run_module(state="stopped")["running"])

    def test_reload_runs_koha_plack_reload(self):
        self.host.states["koha-plack"] = "started"
        result = self.run_module(state="reloaded")
        self.assertTrue(result["changed"])
        self.assertIn(("koha-plack", "--reload"), self.host.log)

    def test_enable_changes_apache_includes_and_asks_for_a_reload(self):
        self.site["content"] = DISABLED
        result = self.run_module(enabled=True)
        self.assertTrue(result["changed"] and result["enabled"] and result["apache_reload_required"])
        self.assertNotIn(("apache2ctl", "graceful"), self.host.log)
        self.assertFalse(self.run_module(enabled=True)["changed"])

    def test_reload_apache_only_when_the_configuration_changed(self):
        self.site["content"] = DISABLED
        result = self.run_module(enabled=True, reload_apache=True)
        self.assertFalse(result["apache_reload_required"])
        self.assertIn(("apache2ctl", "graceful"), self.host.log)
        self.host.log.clear()
        self.run_module(enabled=True, reload_apache=True)
        self.assertNotIn(("apache2ctl", "graceful"), self.host.log)

    def test_disable_does_not_need_the_apache_modules(self):
        self.apache["modules"] = ""
        result = self.run_module(enabled=False)
        self.assertTrue(result["changed"] and not result["enabled"])

    def test_missing_apache_modules_fail_before_changing_anything(self):
        self.site["content"] = DISABLED
        self.apache["modules"] = " headers_module (shared)\n"
        result = self.run_module(enabled=True)
        self.assertTrue(result["failed"])
        self.assertIn("proxy_http", result["msg"])
        self.assertFalse(result["changed"])
        self.assertEqual([op for key, op in self.host.log if key == "koha-plack"], [])

    def test_failed_start_after_enable_still_reports_the_change(self):
        self.site["content"] = DISABLED
        self.host.fail.add(("koha-plack", "--start"))
        self.host.extra["koha-plack"] = lambda argv: (
            (1, "", "boom") if argv[1] == "--start" else self.koha_plack(argv))
        result = self.run_module(enabled=True, state="started")
        self.assertTrue(result["failed"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["actions"], ["enable", "start"])

    def test_check_mode_projects_without_running(self):
        FakeAnsibleModule.check_mode = True
        self.site["content"] = DISABLED
        result = self.run_module(enabled=True, state="started")
        self.assertTrue(result["changed"] and result["planned"] and result["running"])
        self.assertEqual([op for key, op in self.host.log if key == "koha-plack"], [])
        self.assertEqual(self.site["content"], DISABLED)

    def test_status_cannot_be_combined_with_enabled(self):
        self.assertIn("solo lectura", self.run_module(state="status", enabled=True)["msg"])

    def test_inconsistent_includes_fail(self):
        self.site["content"] = ENABLED.splitlines()[0] + "\n" + DISABLED.splitlines()[1] + "\n"
        self.assertIn("inconsistente", self.run_module(state="status")["msg"])


if __name__ == "__main__":
    unittest.main()
