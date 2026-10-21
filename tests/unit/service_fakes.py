# SPDX-License-Identifier: MIT-0
"""Fakes shared by the unit tests of the daemon modules (zebra, zebra_indexer, worker, plack)."""

import contextlib
import importlib.util
import os
import sys
import types
from unittest import mock

# Import once, before any sys.modules patching, so modules and patches share one instance.
from ansible_collections.jmz.koha.plugins.module_utils import koha_service  # noqa: E402,F401


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


class ModuleExit(Exception):
    def __init__(self, result):
        self.result = result


class FakeAnsibleModule:
    """Stands in for AnsibleModule: applies the argument_spec defaults and records commands."""

    params = {}
    check_mode = False
    runner = None
    last = None
    diff = False

    def __init__(self, argument_spec=None, **kwargs):
        self.params = {key: spec.get("default") for key, spec in (argument_spec or {}).items()}
        self.params.update(type(self).params)
        self.check_mode = type(self).check_mode
        self._diff = type(self).diff
        self.commands = []
        type(self).last = self

    def get_bin_path(self, name, required=False, opt_dirs=None):
        # "timeout" is absent on purpose: commands then reach the runner unwrapped.
        return None if name == "timeout" else "/usr/sbin/" + name

    def run_command(self, argv, **kwargs):
        self.commands.append(list(argv))
        return type(self).runner(list(argv))

    def exit_json(self, **kwargs):
        raise ModuleExit(kwargs)

    def fail_json(self, **kwargs):
        kwargs.setdefault("failed", True)
        raise ModuleExit(kwargs)


def load_module(name):
    ansible = types.ModuleType("ansible")
    ansible_utils = types.ModuleType("ansible.module_utils")
    basic = types.ModuleType("ansible.module_utils.basic")
    basic.AnsibleModule = FakeAnsibleModule
    spec = importlib.util.spec_from_file_location(name + "_module_test", os.path.join(ROOT, "plugins/modules/%s.py" % name))
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"ansible": ansible, "ansible.module_utils": ansible_utils,
                                      "ansible.module_utils.basic": basic}):
        spec.loader.exec_module(module)
    return module


def patch_host(testcase, module, *, root=True, files=None, indexer_default=None):
    """Patch the filesystem, privileges, locks and sleeping that the shared helpers touch."""
    from ansible_collections.jmz.koha.plugins.module_utils import koha_service as svc
    files = files if files is not None else set()
    patches = [
        mock.patch.object(svc.os.path, "isfile", side_effect=lambda path: path in files or path.endswith("koha-conf.xml")
                          or path.endswith("koha-preferences")),
        mock.patch.object(svc.os, "access", return_value=True),
        mock.patch.object(svc.os, "geteuid", return_value=0 if root else 1000),
        mock.patch.object(svc, "service_lock", lambda instance: contextlib.nullcontext()),
        mock.patch.object(svc, "static_default", lambda name: indexer_default.get(name) if indexer_default else None),
        mock.patch.object(svc.time, "sleep"),
    ]
    for patcher in patches:
        patcher.start()
        testcase.addCleanup(patcher.stop)
    return svc


class FakeHost:
    """Simulates koha-list and the koha-<daemon> --status/--start/--stop/--restart commands."""

    LABELS = {"koha-zebra": "Zebra", "koha-indexer": "Indexer", "koha-worker": "Worker", "koha-plack": "Plack"}

    def __init__(self, **states):
        self.states = {"koha-zebra": "started", "koha-indexer": "started", "koha-plack": "stopped",
                      "koha-worker/default": "started", "koha-worker/long_tasks": "started"}
        self.states.update({key.replace("__", "/"): value for key, value in states.items()})
        self.fail = set()
        self.log = []
        self.extra = {}

    def __call__(self, argv):
        command = os.path.basename(argv[0])
        if command in self.extra:
            return self.extra[command](argv)
        if command == "koha-list":
            return 0, "biblioteca\narchivo\n", ""
        if command not in self.LABELS:
            return 0, "", ""
        key = command + ("/" + argv[argv.index("--queue") + 1] if "--queue" in argv else "")
        operation = argv[1]
        label = self.LABELS[command]
        if operation == "--status":
            if self.states[key] == "started":
                return 0, " * %s running for biblioteca\n" % label, ""
            return 3, " * %s not running for biblioteca\n" % label, ""
        if operation in ("--start", "--stop", "--restart", "--reload"):
            self.log.append((key, operation))
            if (key, operation) in self.fail:
                return 1, "", "boom"
            if operation != "--reload":
                self.states[key] = "stopped" if operation == "--stop" else "started"
            return 0, "", ""
        return 0, "", ""
