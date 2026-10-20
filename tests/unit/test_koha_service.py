# SPDX-License-Identifier: MIT-0
"""Unit tests for the shared daemon helpers."""

import unittest
from unittest import mock

from ansible_collections.jmz.koha.plugins.module_utils import koha_service as svc


class FakeModule:
    def __init__(self, results, timeout_binary=True):
        self.results, self.commands, self.timeout_binary = list(results), [], timeout_binary

    def get_bin_path(self, name, required=False, opt_dirs=None):
        return "/usr/bin/timeout" if name == "timeout" and self.timeout_binary else None

    def run_command(self, argv):
        self.commands.append(argv)
        return self.results.pop(0)


class StatusParsingTest(unittest.TestCase):
    def test_not_running_is_checked_before_running(self):
        self.assertEqual(svc.parse_status("zebra", "x", 3, " * Zebra not running for x\n", ""), "stopped")
        self.assertEqual(svc.parse_status("zebra", "x", 0, " * Zebra running for x\n", ""), "started")

    def test_exit_status_three_means_stopped_when_text_is_silent(self):
        self.assertEqual(svc.parse_status("zebra", "x", 3, "", ""), "stopped")

    def test_unknown_output_is_an_error(self):
        with self.assertRaises(svc.ServiceError):
            svc.parse_status("zebra", "x", 1, "garbage", "")


class RunTest(unittest.TestCase):
    def test_commands_are_wrapped_with_timeout_and_a_kill_deadline(self):
        module = FakeModule([(0, "ok", "")])
        diagnostics = []
        svc.run(module, ["koha-zebra", "--status", "x"], diagnostics, "status", 30)
        self.assertEqual(module.commands[0][:5], ["/usr/bin/timeout", "-k", "5", "30", "koha-zebra"])
        self.assertEqual(diagnostics[0]["command"], ["koha-zebra", "--status", "x"])

    def test_timeout_status_is_reported_as_an_error(self):
        for rc in (124, 137):
            with self.assertRaises(svc.ServiceError) as raised:
                svc.run(FakeModule([(rc, "", "")]), ["/usr/sbin/koha-zebra", "--start", "x"], [], "start", 30)
            self.assertIn("30 segundos", str(raised.exception))

    def test_without_timeout_binary_the_command_runs_unwrapped(self):
        module = FakeModule([(0, "", "")], timeout_binary=False)
        svc.run(module, ["koha-zebra"], [], "status", 30)
        self.assertEqual(module.commands[0], ["koha-zebra"])


class StaticDefaultTest(unittest.TestCase):
    def read(self, content):
        with mock.patch.object(svc.os.path, "isfile", return_value=True), \
                mock.patch("builtins.open", mock.mock_open(read_data=content)):
            return svc.static_default("ALTERNATE_INDEXER_DAEMON")

    def test_simple_assignment_comments_and_absence(self):
        self.assertEqual(self.read('ALTERNATE_INDEXER_DAEMON="/usr/bin/x"\n'), "/usr/bin/x")
        self.assertIsNone(self.read("# ALTERNATE_INDEXER_DAEMON=/usr/bin/x\nOTHER=1\n"))
        self.assertIsNone(self.read('ALTERNATE_INDEXER_DAEMON=""\n'))

    def test_dynamic_values_are_refused(self):
        for content in ('ALTERNATE_INDEXER_DAEMON=$(whoami)\n', 'ALTERNATE_INDEXER_DAEMON=a b\n',
                        'export ALTERNATE_INDEXER_DAEMON=`id`\n', 'if true; then ALTERNATE_INDEXER_DAEMON=x; fi\n'):
            with self.assertRaises(svc.ServiceError):
                self.read(content)


class PlanTest(unittest.TestCase):
    def test_plans(self):
        self.assertEqual(svc.plan("started", "stopped"), ["start"])
        self.assertEqual(svc.plan("started", "started"), [])
        self.assertEqual(svc.plan("stopped", "started"), ["stop"])
        self.assertEqual(svc.plan("restarted", "stopped"), ["restart"])
        self.assertEqual(svc.plan("status", "stopped"), [])


if __name__ == "__main__":
    unittest.main()
