# SPDX-License-Identifier: MIT-0
"""Unit tests for zebra_rebuild; Koha commands and system state are mocked."""

import unittest
from unittest import mock

from tests.unit.service_fakes import FakeAnsibleModule, ModuleExit, load_module, patch_host


FULL_HELP = "--full --biblios --authorities --force --verbose --quiet --help"


class ZebraRebuildTest(unittest.TestCase):
    def setUp(self):
        FakeAnsibleModule.params = {"instance": "biblioteca"}
        FakeAnsibleModule.check_mode = False
        self.module = load_module("zebra_rebuild")
        # USE_INDEXER_DAEMON="no": incremental work runs.
        self.svc = patch_host(self, self.module, indexer_default={"USE_INDEXER_DAEMON": "no"})

    def run_module(self, *, engine="Zebra", zebra=True, result_text="Processing selected indexes\n", rc=0,
                   fail_target=None, help_text=FULL_HELP, timeout_target=None):
        def runner(argv):
            name = argv[0].rsplit("/", 1)[-1]
            if name == "koha-list":
                return 0, "biblioteca\narchivo\n", ""
            if name == "koha-rebuild-zebra" and "--help" in argv:
                return 0, help_text, ""
            if name == "koha-shell":
                return 0, engine + "\n", ""
            if name == "koha-zebra":
                return (0, " * Zebra running for biblioteca\n", "") if zebra else (3, " * Zebra not running for biblioteca\n", "")
            if name == "koha-rebuild-zebra":
                target = "biblios" if "--biblios" in argv else "authorities"
                if fail_target == target:
                    return 0, "", "Something went wrong rebuilding %s indexes for biblioteca" % ("biblio" if target == "biblios" else "authority")
                return rc, result_text, ""
            return 0, "", ""
        FakeAnsibleModule.runner = runner
        with self.assertRaises(ModuleExit) as raised:
            self.module.main()
        return raised.exception.result, FakeAnsibleModule.last.commands

    @staticmethod
    def rebuilds(commands):
        return [c for c in commands if c[0].endswith("koha-rebuild-zebra") and "--help" not in c]

    def test_target_and_mode_arguments(self):
        for target, expected_flag in (("biblios", "--biblios"), ("authorities", "--authorities"), ("all", None)):
            FakeAnsibleModule.params = {"instance": "biblioteca", "target": target}
            result, commands = self.run_module()
            rebuilds = self.rebuilds(commands)
            self.assertEqual(len(rebuilds), 2 if target == "all" else 1)
            if expected_flag:
                self.assertIn(expected_flag, rebuilds[0])
            self.assertEqual(result["status"], "completed")
        for target in ("biblios", "authorities", "all"):
            FakeAnsibleModule.params = {"instance": "biblioteca", "mode": "full", "target": target, "verbose": 0}
            _, commands = self.run_module()
            self.assertTrue(all("--full" in c for c in self.rebuilds(commands)))

    def test_force_and_option_validation(self):
        FakeAnsibleModule.params = {"instance": "biblioteca", "force": True}
        result, commands = self.run_module()
        self.assertTrue(any("--force" in c for c in commands))
        self.assertTrue(result["changed"])
        FakeAnsibleModule.params = {"instance": "biblioteca", "mode": "full", "force": True}
        result, commands = self.run_module()
        self.assertIn("solo es válido", result["msg"])
        self.assertEqual(commands, [])
        FakeAnsibleModule.params = {"instance": "biblioteca", "quiet": True}
        self.assertIn("incompatible", self.run_module()[0]["msg"])
        FakeAnsibleModule.params = {"instance": "biblioteca", "quiet": True, "verbose": 0}
        result, commands = self.run_module()
        self.assertTrue(any("--quiet" in c for c in commands))
        FakeAnsibleModule.params = {"instance": "biblioteca", "verbose": 3}
        _, commands = self.run_module()
        self.assertEqual(self.rebuilds(commands)[0].count("--verbose"), 3)
        FakeAnsibleModule.params = {"instance": "biblioteca", "timeout": 0}
        self.assertIn("timeout", self.run_module()[0]["msg"])

    def test_instance_engine_permissions_and_zebra_checks(self):
        FakeAnsibleModule.params = {"instance": "../x"}
        self.assertIn("instance debe", self.run_module()[0]["msg"])
        FakeAnsibleModule.params = {"instance": "biblioteca", "verify_search_engine": True}
        self.assertIn("SearchEngine es Elasticsearch", self.run_module(engine="Elasticsearch")[0]["msg"])
        FakeAnsibleModule.params = {"instance": "biblioteca", "require_zebra_running": True}
        self.assertIn("Zebra está detenido", self.run_module(zebra=False)[0]["msg"])
        FakeAnsibleModule.params = {"instance": "biblioteca"}
        with mock.patch.object(self.svc.os, "geteuid", return_value=1000):
            self.assertIn("become: true", self.run_module()[0]["msg"])

    def test_incremental_daemon_skip_force_and_check_mode(self):
        with mock.patch.object(self.module, "inspect_indexer_configuration", return_value="enabled_or_unset"):
            result, commands = self.run_module()
        self.assertEqual(result["status"], "skipped")
        self.assertFalse(result["changed"])
        # Ansible shows a task as SKIPPED when the result has a "skipped" key; the module uses work_skipped.
        self.assertTrue(result["work_skipped"])
        self.assertNotIn("skipped", result)
        self.assertFalse(result.get("failed"))
        self.assertEqual(self.rebuilds(commands), [])
        FakeAnsibleModule.params = {"instance": "biblioteca", "force": True}
        with mock.patch.object(self.module, "inspect_indexer_configuration", return_value="enabled_or_unset"):
            result, commands = self.run_module()
        self.assertEqual(result["status"], "completed")
        self.assertTrue(any("--force" in c for c in commands))
        FakeAnsibleModule.check_mode = True
        FakeAnsibleModule.params = {"instance": "biblioteca", "mode": "full", "target": "biblios"}
        result, commands = self.run_module()
        self.assertTrue(result["changed"])
        self.assertFalse(result["executed"])
        self.assertTrue(result["command"])
        self.assertEqual(self.rebuilds(commands), [])

    def test_nonzero_internal_error_partial_and_unknown_results(self):
        result, _ = self.run_module(rc=4)
        self.assertTrue(result["failed"])
        self.assertTrue(result["changed"])
        result, _ = self.run_module(fail_target="biblios")
        self.assertTrue(result["failed"])
        self.assertEqual(result["target_results"]["biblios"]["status"], "failed")
        self.assertEqual(result["target_results"]["authorities"]["status"], "completed")
        result, _ = self.run_module(fail_target="authorities")
        self.assertEqual(result["target_results"]["biblios"]["status"], "completed")
        self.assertEqual(result["target_results"]["authorities"]["status"], "failed")
        # A quiet run exits 0 with no output; that is a completed rebuild.
        result, _ = self.run_module(result_text="")
        self.assertFalse(result.get("failed"))
        self.assertEqual(result["status"], "completed")
        result, _ = self.run_module(result_text="Skipped bibliographic indexing because work is unavailable")
        self.assertEqual(result["status"], "skipped")
        self.assertFalse(result["changed"])
        self.assertTrue(result["work_skipped"])

    def test_generic_words_only_matter_when_the_command_failed(self):
        # A record title containing "error" must not turn a successful rebuild into a failure.
        result, _ = self.run_module(result_text="Indexing: The Book of Errors, a warning to all\nerror in title\n")
        self.assertEqual(result["status"], "completed")
        result, _ = self.run_module(rc=2, result_text="fatal: something broke")
        self.assertEqual(result["status"], "failed")

    def test_lock_warnings_and_cli_compatibility(self):
        result, _ = self.run_module(result_text="Could not obtain lock; another rebuild is active")
        self.assertTrue(result["failed"])
        self.assertEqual(result["status"], "blocked")
        result, _ = self.run_module(result_text="Continuing without lock")
        self.assertEqual(result["status"], "blocked")
        FakeAnsibleModule.params = {"instance": "biblioteca", "mode": "full"}
        result, _ = self.run_module(help_text="--full --biblios --authorities --help")
        self.assertIn("no anuncia la opción requerida --verbose", result["msg"])

    def test_unlisted_instance_and_engine_query_fail_closed(self):
        FakeAnsibleModule.params = {"instance": "otra"}
        self.assertIn("koha-list", self.run_module()[0]["msg"])
        FakeAnsibleModule.params = {"instance": "biblioteca", "verify_search_engine": True}
        def bad_preference(argv):
            name = argv[0].rsplit("/", 1)[-1]
            if name == "koha-list":
                return 0, "biblioteca\n", ""
            if name == "koha-rebuild-zebra":
                return 0, FULL_HELP, ""
            if name == "koha-shell":
                return 1, "", "database unavailable"
            return 0, "", ""
        FakeAnsibleModule.runner = bad_preference
        with self.assertRaises(ModuleExit) as raised:
            self.module.main()
        self.assertIn("no se pudo leer SearchEngine", raised.exception.result["msg"])

    def test_timed_out_pass_is_a_failed_target_and_stops_the_run(self):
        def runner(argv):
            name = argv[0].rsplit("/", 1)[-1]
            if name == "koha-list":
                return 0, "biblioteca\n", ""
            if name == "koha-rebuild-zebra" and "--help" in argv:
                return 0, FULL_HELP, ""
            if name == "koha-shell":
                return 0, "Zebra\n", ""
            return 0, "", ""
        FakeAnsibleModule.runner = runner
        with mock.patch.object(self.module.svc, "run", side_effect=self.timeout_after_validation(runner)):
            with self.assertRaises(ModuleExit) as raised:
                self.module.main()
        result = raised.exception.result
        self.assertTrue(result["failed"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["target_results"]["biblios"]["status"], "failed")
        self.assertFalse(result["target_results"]["authorities"]["executed"])

    def timeout_after_validation(self, runner):
        def run(module, argv, diagnostics, operation, timeout):
            if operation.startswith("rebuild_"):
                raise self.module.svc.ServiceError("koha-rebuild-zebra excedió el límite de %s segundos" % timeout)
            return runner(argv)
        return run

    def test_dynamic_indexer_setting_fails_safely(self):
        with mock.patch.object(self.module, "inspect_indexer_configuration",
                               side_effect=self.module.RebuildError("dynamic setting")):
            self.assertIn("dynamic setting", self.run_module()[0]["msg"])

    def test_repeated_imperative_invocations_run_each_time(self):
        first, commands1 = self.run_module()
        second, commands2 = self.run_module()
        self.assertTrue(first["changed"] and second["changed"])
        self.assertEqual(len(self.rebuilds(commands1)), 2)
        self.assertEqual(len(self.rebuilds(commands2)), 2)

    def test_instances_are_scoped_and_results_are_structured(self):
        FakeAnsibleModule.params = {"instance": "archivo", "target": "biblios", "verbose": 0}
        result, commands = self.run_module()
        rebuilds = self.rebuilds(commands)
        self.assertEqual(len(rebuilds), 1)
        self.assertEqual(rebuilds[0][-1], "archivo")
        for key in ("instance", "mode", "target", "status", "executed", "work_skipped", "skip_reason",
                    "command", "rc", "duration", "search_engine", "zebra_running", "target_results", "stdout", "stderr", "msg"):
            self.assertIn(key, result)
        self.assertIsNone(result["target_results"]["biblios"]["records_processed"])


if __name__ == "__main__":
    unittest.main()
