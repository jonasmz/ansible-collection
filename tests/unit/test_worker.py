# SPDX-License-Identifier: MIT-0
import importlib.util
import os
import sys
import types
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
HELP = "koha-worker --start --stop --restart --enable --disable --queue --all-queues --status --quiet"


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
        self._diff = False
        self.commands = []
        previous = type(self).last
        self.states = ({queue: dict(state) for queue, state in previous.states.items()} if previous else
                       {"default": {"running": True, "enabled": True},
                        "long_tasks": {"running": True, "enabled": True}})
        self.responses = list(previous.responses) if previous else []
        self.failed_queues = set(previous.failed_queues) if previous else set()
        type(self).last = self

    def get_bin_path(self, name, required=False):
        return {"koha-worker": "/usr/sbin/koha-worker", "systemctl": "/usr/bin/systemctl"}.get(name)

    def run_command(self, argv, **kwargs):
        self.commands.append(argv)
        if argv[0] == "/usr/sbin/koha-worker" and argv[1] == "--help":
            return 0, HELP, ""
        if self.responses:
            response = self.responses.pop(0)
            return response
        if argv[0] == "/usr/bin/systemctl":
            unit = argv[-1]
            queue = "long_tasks" if "long_tasks" in unit else "default"
            state = self.states[queue]
            active = "active" if state["running"] else "inactive"
            enabled = "enabled" if state["enabled"] else "disabled"
            return 0, "LoadState=loaded\nActiveState=%s\nSubState=%s\nUnitFileState=%s\n" % (
                active, "running" if state["running"] else "dead", enabled), ""
        action = argv[1]
        if action == "--status":
            queue = argv[argv.index("--queue") + 1]
            verb = "running" if self.states[queue]["running"] else "not running"
            name = argv[-1]
            return 0, "worker %s for %s (%s)\n" % (verb, name, queue), ""
        queues = ["default", "long_tasks"] if "--all-queues" in argv else [argv[argv.index("--queue") + 1]]
        for queue in queues:
            if queue in self.failed_queues:
                continue
            if action == "--start":
                self.states[queue]["running"] = True
            elif action == "--stop":
                self.states[queue]["running"] = False
            elif action == "--restart":
                self.states[queue]["running"] = True
            elif action == "--enable":
                self.states[queue]["enabled"] = True
            elif action == "--disable":
                self.states[queue]["enabled"] = False
        return 0, "ok", ""

    def exit_json(self, **kwargs):
        raise ModuleExit(kwargs)

    def fail_json(self, **kwargs):
        raise ModuleExit(kwargs)


def load_module():
    ansible = types.ModuleType("ansible")
    ansible_utils = types.ModuleType("ansible.module_utils")
    basic = types.ModuleType("ansible.module_utils.basic")
    basic.AnsibleModule = FakeAnsibleModule
    spec = importlib.util.spec_from_file_location("worker_module_test", os.path.join(ROOT, "plugins/modules/worker.py"))
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"ansible": ansible, "ansible.module_utils": ansible_utils,
                                      "ansible.module_utils.basic": basic}):
        spec.loader.exec_module(module)
    return module


class WorkerModuleTest(unittest.TestCase):
    def setUp(self):
        FakeAnsibleModule.params = {"name": "biblioteca", "state": "status", "queue": "default", "quiet": False}
        FakeAnsibleModule.check_mode = False
        FakeAnsibleModule.last = None
        self.module = load_module()
        templates = ("koha-worker@.service", "koha-worker-long_tasks@.service")
        self._file_patch = mock.patch.object(
            self.module.os.path, "isfile",
            side_effect=lambda path: path == "/etc/koha/sites/biblioteca/koha-conf.xml" or
            any(path.endswith(template) for template in templates),
        )
        self._file_patch.start()
        self.addCleanup(self._file_patch.stop)
        self._dir_patch = mock.patch.object(
            self.module.os.path, "isdir", side_effect=lambda path: path == "/etc/koha/sites/biblioteca"
        )
        self._dir_patch.start()
        self.addCleanup(self._dir_patch.stop)
        self._root_patch = mock.patch.object(self.module.os, "geteuid", return_value=0)
        self._root_patch.start()
        self.addCleanup(self._root_patch.stop)

    def _run(self, missing_binary=False):
        module = FakeAnsibleModule.last
        # Build the fake AnsibleModule inside main; ensure deterministic state per invocation.
        with self.assertRaises(ModuleExit) as raised:
            self.module.main()
        return raised.exception.result, FakeAnsibleModule.last.commands

    def test_start_and_idempotent_second_run(self):
        FakeAnsibleModule.params.update(state="started")
        FakeAnsibleModule.last = FakeAnsibleModule()
        FakeAnsibleModule.last.states["default"]["running"] = False
        result, commands = self._run()
        self.assertTrue(result["changed"])
        self.assertEqual(result["workers"]["default"]["status"], "running")
        self.assertIn("--start", commands[2])
        result, commands = self._run()
        self.assertFalse(result["changed"])
        self.assertFalse(any("--start" in command for command in commands))

    def test_stop_and_second_run_are_idempotent(self):
        FakeAnsibleModule.params.update(state="stopped")
        FakeAnsibleModule.last = FakeAnsibleModule()
        result, commands = self._run()
        self.assertTrue(result["changed"])
        self.assertIn("--stop", commands[2])
        result, commands = self._run()
        self.assertFalse(result["changed"])
        self.assertFalse(any("--stop" in command for command in commands))

    def test_restart_active_and_stopped_are_explicit(self):
        FakeAnsibleModule.params.update(state="restarted")
        result, commands = self._run()
        self.assertTrue(result["changed"])
        self.assertIn("--restart", commands[2])
        FakeAnsibleModule.params["queue"] = "long_tasks"
        FakeAnsibleModule.last = FakeAnsibleModule()
        FakeAnsibleModule.last.states["long_tasks"]["running"] = False
        result, commands = self._run()
        self.assertTrue(result["changed"])
        self.assertIn("--restart", commands[2])
        self.assertTrue(result["workers"]["long_tasks"]["running"])

    def test_status_and_independent_queues(self):
        result, commands = self._run()
        self.assertFalse(result["changed"])
        self.assertEqual(result["workers"].keys(), {"default"})
        FakeAnsibleModule.params["queue"] = "long_tasks"
        result, _ = self._run()
        self.assertEqual(result["workers"].keys(), {"long_tasks"})

    def test_all_queues_use_official_all_switch(self):
        FakeAnsibleModule.params.update(state="started", queue="all")
        FakeAnsibleModule.last = FakeAnsibleModule()
        FakeAnsibleModule.last.states["default"]["running"] = False
        FakeAnsibleModule.last.states["long_tasks"]["running"] = False
        result, commands = self._run()
        self.assertTrue(result["changed"])
        self.assertIn("--all-queues", commands[3])
        self.assertEqual(set(result["workers"]), {"default", "long_tasks"})

    def test_systemd_enable_and_idempotency(self):
        FakeAnsibleModule.params.update(state="started", queue="all", enabled=True)
        result, commands = self._run()
        self.assertFalse(result["changed"])
        self.assertFalse(any("--enable" in command for command in commands))
        FakeAnsibleModule.last = FakeAnsibleModule()
        FakeAnsibleModule.last.states["default"]["enabled"] = False
        FakeAnsibleModule.last.states["long_tasks"]["enabled"] = False
        FakeAnsibleModule.params.update(state="started")
        result, commands = self._run()
        self.assertTrue(result["changed"])
        self.assertIn("--enable", commands[3])
        self.assertIn("--all-queues", commands[3])

    def test_check_mode_plans_without_mutating(self):
        FakeAnsibleModule.params.update(state="started", queue="all", enabled=True)
        FakeAnsibleModule.check_mode = True
        FakeAnsibleModule.last = FakeAnsibleModule()
        FakeAnsibleModule.last.states["default"].update(running=False, enabled=False)
        FakeAnsibleModule.last.states["long_tasks"].update(running=False, enabled=False)
        result, commands = self._run()
        self.assertTrue(result["changed"])
        self.assertEqual(result["workers"]["default"]["running"], True)
        self.assertEqual(result["workers"]["default"]["enabled"], True)
        self.assertFalse(any("--start" in c or "--enable" in c for c in commands))

    def test_validation_and_incompatible_status(self):
        FakeAnsibleModule.params["name"] = "Biblioteca"
        result, commands = self._run()
        self.assertIn("válido", result["msg"])
        self.assertEqual(commands, [])
        FakeAnsibleModule.params.update(name="biblioteca", enabled=False)
        result, commands = self._run()
        self.assertIn("solo lectura", result["msg"])
        self.assertEqual(commands, [])

    def test_missing_instance_and_unknown_status_fail(self):
        # Unknown systemd active state is not treated as stopped.
        FakeAnsibleModule.last = FakeAnsibleModule()
        FakeAnsibleModule.last.responses = [(
            0, "LoadState=loaded\nActiveState=activating\nSubState=start\nUnitFileState=enabled\n", ""
        )]
        result, _ = self._run()
        self.assertIn("no interpretable", result["msg"])
        with mock.patch.object(self.module.os.path, "isfile", return_value=False):
            result, _ = self._run()
            self.assertIn("no existe", result["msg"])

    def test_commands_are_argument_vectors_and_instance_scoped(self):
        FakeAnsibleModule.params.update(name="biblioteca", state="started")
        FakeAnsibleModule.last = FakeAnsibleModule()
        FakeAnsibleModule.last.states["default"]["running"] = False
        _, commands = self._run()
        self.assertTrue(all(isinstance(command, list) for command in commands))
        self.assertNotIn("otra", str(commands))
        self.assertEqual(commands[2][-1], "biblioteca")

    def test_sysv_status_and_enablement_limitation(self):
        with mock.patch.object(
            self.module.os.path, "isfile",
            side_effect=lambda path: path == "/etc/koha/sites/biblioteca/koha-conf.xml",
        ):
            FakeAnsibleModule.last = FakeAnsibleModule()
            result, commands = self._run()
            self.assertEqual(result["backend"], "sysv")
            self.assertIsNone(result["workers"]["default"]["enabled"])
            self.assertEqual(commands[1][1], "--status")
            FakeAnsibleModule.params.update(enabled=True, state="started")
            result, _ = self._run()
            self.assertIn("backend SysV", result["msg"])

    def test_partial_start_failure_reports_each_queue(self):
        FakeAnsibleModule.params.update(state="started", queue="all")
        FakeAnsibleModule.last = FakeAnsibleModule()
        FakeAnsibleModule.last.states["default"]["running"] = False
        FakeAnsibleModule.last.states["long_tasks"]["running"] = False
        FakeAnsibleModule.last.failed_queues.add("long_tasks")
        result, commands = self._run()
        self.assertIn("falló", result["msg"])
        self.assertTrue(result["workers"]["default"]["running"])
        self.assertFalse(result["workers"]["long_tasks"]["running"])
        self.assertTrue(result["workers"]["default"]["changed"])
        self.assertFalse(result["workers"]["long_tasks"]["changed"])
        self.assertTrue(any("--all-queues" in command for command in commands))

    def test_start_that_remains_stopped_fails(self):
        FakeAnsibleModule.params.update(state="started")
        FakeAnsibleModule.last = FakeAnsibleModule()
        FakeAnsibleModule.last.states["default"]["running"] = False
        FakeAnsibleModule.last.failed_queues.add("default")
        result, _ = self._run()
        self.assertIn("falló", result["msg"])
        self.assertEqual(result["workers"]["default"]["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
