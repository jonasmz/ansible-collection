# SPDX-License-Identifier: MIT-0
"""Unit tests for the Zebra indexer module; Koha commands are simulated with their real output format."""

import unittest

from tests.unit.service_fakes import FakeAnsibleModule, FakeHost, ModuleExit, load_module, patch_host


class ZebraIndexerTest(unittest.TestCase):
    def setUp(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "state": "started"}
        FakeAnsibleModule.check_mode = False
        self.module = load_module("zebra_indexer")
        self.host = FakeHost()
        FakeAnsibleModule.runner = self.host
        self.patch(indexer_default=None)

    def patch(self, **kwargs):
        patch_host(self, self.module, **kwargs)

    def run_module(self, **params):
        FakeAnsibleModule.params.update(params)
        with self.assertRaises(ModuleExit) as raised:
            self.module.main()
        return raised.exception.result

    def mutations(self):
        return [op for key, op in self.host.log if key == "koha-indexer"]

    def test_stop_start_and_idempotence_with_real_status_text(self):
        result = self.run_module(state="stopped")
        self.assertTrue(result["changed"])
        self.assertFalse(self.run_module(state="stopped")["changed"])
        self.assertTrue(self.run_module(state="started")["changed"])
        self.assertFalse(self.run_module(state="started")["changed"])
        self.assertEqual(self.mutations(), ["--stop", "--start"])

    def test_check_mode_and_status_do_not_change_anything(self):
        FakeAnsibleModule.check_mode = True
        result = self.run_module(state="stopped")
        self.assertTrue(result["changed"] and result["planned"])
        FakeAnsibleModule.check_mode = False
        self.assertFalse(self.run_module(state="status")["changed"])
        self.assertEqual(self.mutations(), [])

    def test_search_engine_must_be_zebra_to_start(self):
        self.host.states["koha-indexer"] = "stopped"
        self.host.extra["koha-shell"] = lambda argv: (0, "Elasticsearch\n", "")
        result = self.run_module(verify_zebra_engine=True)
        self.assertTrue(result["failed"])
        self.assertIn("Elasticsearch", result["msg"])
        self.assertEqual(self.mutations(), [])
        self.host.extra["koha-shell"] = lambda argv: (0, "Zebra\n", "")
        result = self.run_module(verify_zebra_engine=True)
        self.assertEqual(result["search_engine"], "Zebra")
        self.assertTrue(result["changed"])

    def test_stopping_does_not_need_the_zebra_engine(self):
        self.host.extra["koha-shell"] = lambda argv: (0, "Elasticsearch\n", "")
        self.assertTrue(self.run_module(state="stopped", verify_zebra_engine=True)["changed"])

    def test_require_zebra_running(self):
        self.host.states.update({"koha-indexer": "stopped", "koha-zebra": "stopped"})
        result = self.run_module(require_zebra_running=True)
        self.assertTrue(result["failed"])
        self.assertEqual(self.mutations(), [])
        self.host.states["koha-zebra"] = "started"
        result = self.run_module(require_zebra_running=True)
        self.assertTrue(result["zebra_running"])
        self.assertTrue(result["changed"])

    def test_alternate_indexer_blocks_changes_but_not_reads(self):
        self.patch(indexer_default={"ALTERNATE_INDEXER_DAEMON": "/usr/local/bin/other"})
        self.assertIn("ALTERNATE_INDEXER_DAEMON", self.run_module(state="stopped")["msg"])
        self.assertFalse(self.run_module(state="started")["changed"])
        self.assertEqual(self.mutations(), [])

    def test_quiet_applies_to_changes_only(self):
        self.host.states["koha-indexer"] = "stopped"
        self.run_module(quiet=True)
        starts = [c for c in FakeAnsibleModule.last.commands if len(c) > 1 and c[1] == "--start"]
        self.assertIn("--quiet", starts[0])
        statuses = [c for c in FakeAnsibleModule.last.commands if len(c) > 1 and c[1] == "--status"]
        self.assertTrue(all("--quiet" not in c for c in statuses))


if __name__ == "__main__":
    unittest.main()
