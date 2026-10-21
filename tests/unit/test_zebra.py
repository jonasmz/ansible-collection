# SPDX-License-Identifier: MIT-0
"""Unit tests for the Zebra module; Koha commands are simulated with their real output format."""

import unittest

from tests.unit.service_fakes import FakeAnsibleModule, FakeHost, ModuleExit, load_module, patch_host


class ZebraModuleTest(unittest.TestCase):
    def setUp(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "started"}
        FakeAnsibleModule.check_mode = False
        self.module = load_module("zebra")
        self.host = FakeHost()
        FakeAnsibleModule.runner = self.host
        patch_host(self, self.module)

    def run_module(self, **params):
        FakeAnsibleModule.params.update(params)
        with self.assertRaises(ModuleExit) as raised:
            self.module.main()
        return raised.exception.result

    def mutations(self):
        return [operation for key, operation in self.host.log if key == "koha-zebra"]

    def test_started_when_running_does_nothing(self):
        result = self.run_module()
        self.assertFalse(result["changed"])
        self.assertEqual(self.mutations(), [])
        self.assertEqual((result["previous_state"], result["state"]), ("started", "started"))

    def test_stop_and_start_use_the_real_status_text(self):
        # "not running" contains "running": it must still read as stopped.
        result = self.run_module(state="stopped")
        self.assertTrue(result["changed"])
        self.assertEqual(result["state"], "stopped")
        self.assertFalse(self.run_module(state="stopped")["changed"])
        result = self.run_module(state="started")
        self.assertTrue(result["changed"])
        self.assertEqual(self.mutations(), ["--stop", "--start"])

    def test_restart_always_changes(self):
        result = self.run_module(state="restarted")
        self.assertTrue(result["changed"])
        self.assertEqual(result["actions"], ["restart"])

    def test_status_is_read_only_and_default(self):
        FakeAnsibleModule.params.pop("state")
        FakeAnsibleModule.params["state"] = "status"
        result = self.run_module()
        self.assertFalse(result["changed"])
        self.assertEqual(self.mutations(), [])

    def test_check_mode_plans_without_running(self):
        FakeAnsibleModule.check_mode = True
        result = self.run_module(state="stopped")
        self.assertTrue(result["changed"] and result["planned"])
        self.assertEqual(result["state"], "stopped")
        self.assertEqual(self.mutations(), [])
        self.assertEqual(self.host.states["koha-zebra"], "started")

    def test_failed_start_reports_the_command_and_changed_false(self):
        self.host.states["koha-zebra"] = "stopped"
        self.host.fail.add(("koha-zebra", "--start"))
        result = self.run_module()
        self.assertTrue(result["failed"])
        self.assertFalse(result["changed"])
        self.assertIn("boom", result["msg"])

    def test_requires_root_to_change_but_not_to_read(self):
        patch_host(self, self.module, root=False)
        self.assertTrue(self.run_module(state="restarted")["failed"])
        self.assertFalse(self.run_module(state="status").get("failed"))

    def test_rejects_unknown_instances_and_bad_timeouts(self):
        self.assertIn("koha-list", self.run_module(instance="otra")["msg"])
        self.assertTrue(self.run_module(instance="Bad_Name")["failed"])
        self.assertIn("timeout", self.run_module(timeout=0)["msg"])

    def test_verbose_is_passed_to_changes_only(self):
        self.host.states["koha-zebra"] = "stopped"
        self.run_module(verbose=True)
        commands = [c for c in FakeAnsibleModule.last.commands if c[0].endswith("koha-zebra")]
        self.assertIn("--verbose", [a for c in commands if c[1] == "--start" for a in c])
        self.assertNotIn("--verbose", [a for c in commands if c[1] == "--status" for a in c])


if __name__ == "__main__":
    unittest.main()
