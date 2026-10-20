# SPDX-License-Identifier: MIT-0
"""Unit tests for the worker module; Koha commands are simulated with their real output format."""

import unittest

from tests.unit.service_fakes import FakeAnsibleModule, FakeHost, ModuleExit, load_module, patch_host


class WorkerModuleTest(unittest.TestCase):
    def setUp(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "started"}
        FakeAnsibleModule.check_mode = False
        self.module = load_module("worker")
        self.host = FakeHost()
        FakeAnsibleModule.runner = self.host
        patch_host(self, self.module)

    def run_module(self, **params):
        FakeAnsibleModule.params.update(params)
        with self.assertRaises(ModuleExit) as raised:
            self.module.main()
        return raised.exception.result

    def test_state_is_optional_and_read_only(self):
        FakeAnsibleModule.params.pop("state")
        result = self.run_module(state="status")
        self.assertFalse(result["changed"])
        self.assertEqual(self.host.log, [])
        self.assertEqual(result["workers"]["default"]["state"], "started")

    def test_default_queue_only_by_default(self):
        self.host.states["koha-worker/default"] = "stopped"
        result = self.run_module()
        self.assertEqual(list(result["workers"]), ["default"])
        self.assertEqual(self.host.log, [("koha-worker/default", "--start")])

    def test_all_queues_are_handled_one_by_one(self):
        self.host.states["koha-worker/long_tasks"] = "stopped"
        result = self.run_module(queue="all")
        self.assertTrue(result["changed"])
        self.assertFalse(result["workers"]["default"]["changed"])
        self.assertTrue(result["workers"]["long_tasks"]["changed"])
        self.assertEqual(result["actions"], ["start:long_tasks"])

    def test_stop_then_repeat_is_idempotent(self):
        self.assertTrue(self.run_module(state="stopped", queue="all")["changed"])
        self.assertFalse(self.run_module(state="stopped", queue="all")["changed"])

    def test_check_mode_projects_without_running(self):
        FakeAnsibleModule.check_mode = True
        result = self.run_module(state="stopped", queue="all")
        self.assertTrue(result["changed"] and result["planned"])
        self.assertEqual(result["workers"]["default"]["state"], "stopped")
        self.assertEqual(self.host.log, [])

    def test_failure_keeps_the_progress_of_earlier_queues(self):
        self.host.states.update({"koha-worker/default": "stopped", "koha-worker/long_tasks": "stopped"})
        self.host.fail.add(("koha-worker/long_tasks", "--start"))
        result = self.run_module(queue="all")
        self.assertTrue(result["failed"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["actions"], ["start:default", "start:long_tasks"])
        self.assertTrue(result["workers"]["default"]["changed"])

    def test_root_is_needed_only_to_change(self):
        patch_host(self, self.module, root=False)
        self.assertTrue(self.run_module(state="restarted")["failed"])
        self.assertFalse(self.run_module(state="status").get("failed"))


if __name__ == "__main__":
    unittest.main()
