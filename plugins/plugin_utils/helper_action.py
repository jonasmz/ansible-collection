# SPDX-License-Identifier: MIT-0
"""Shared action plugin that stages a collection Perl helper on the host and runs a module with it."""

import contextlib
import os
import uuid

from ansible.errors import AnsibleActionFail
from ansible.plugins.action import ActionBase


class HelperActionBase(ActionBase):
    """Copy ``files/<helper_file>`` to a throwaway directory and pass its path as ``<helper_arg>``.

    Subclasses set ``module_name``, ``helper_file``, ``helper_arg`` and ``prefix``; the staged
    path is ``/tmp/ansible-koha-<prefix>-<32 hex>/<helper_file>``, which the modules validate.
    """

    TRANSFERS_FILES = True
    module_name = None
    helper_file = None
    helper_arg = None
    prefix = None

    @contextlib.contextmanager
    def _real_execution(self):
        # Staging and cleanup only touch a private temporary directory. The file and command
        # modules skip their work in check mode, which would leave the module with no helper
        # to run, so these steps must execute for real; the module call itself keeps check mode.
        original = self._task.check_mode
        self._task.check_mode = False
        try:
            yield
        finally:
            self._task.check_mode = original

    def _stage(self, task_vars):
        collection_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        source = os.path.join(collection_root, "files", self.helper_file)
        if not os.path.isfile(source):
            raise AnsibleActionFail("The collection helper files/%s is missing: %s" % (self.helper_file, source))
        # Upload as the connection user first; the shared staging directory is created with
        # become and populated by a privileged copy, so koha-shell can read it.
        upload_tmp = self._make_tmp_path()
        self._cleanup.append(lambda: self._remove_tmp_path(upload_tmp, force=True))
        upload_file = upload_tmp + "/" + self.helper_file
        self._transfer_file(source, upload_file)

        staged = "/tmp/ansible-koha-%s-%s" % (self.prefix, uuid.uuid4().hex)
        self._cleanup.append(lambda: self._execute_module(
            module_name="ansible.builtin.file", module_args={"path": staged, "state": "absent"}, task_vars=task_vars))
        remote_file = staged + "/" + self.helper_file
        steps = (
            ("ansible.builtin.file", {"path": staged, "mode": "0711", "state": "directory"}),
            ("ansible.builtin.command", {"argv": ["/usr/bin/cp", "--", upload_file, remote_file]}),
            # The helper holds no credentials; only this temporary directory is made readable.
            ("ansible.builtin.file", {"path": remote_file, "mode": "0644", "state": "file"}),
        )
        for module_name, module_args in steps:
            step = self._execute_module(module_name=module_name, module_args=module_args, task_vars=task_vars)
            if step.get("failed"):
                return None, step
        return remote_file, None

    def run(self, tmp=None, task_vars=None):
        result = super().run(tmp, task_vars)
        task_vars = task_vars or {}
        self._cleanup = []
        cleanup_warnings = []
        try:
            with self._real_execution():
                remote_file, failure = self._stage(task_vars)
            if failure:
                return failure
            args = dict(self._task.args)
            args[self.helper_arg] = remote_file
            result = self._execute_module(module_name=self.module_name, module_args=args, task_vars=task_vars, tmp=tmp)
        except AnsibleActionFail:
            raise
        except Exception as exc:
            raise AnsibleActionFail("Unable to stage or run the Koha %s helper: %s" % (self.prefix, exc))
        finally:
            with self._real_execution():
                for step in reversed(self._cleanup):
                    try:
                        step()
                    except Exception as exc:
                        cleanup_warnings.append("Could not remove a temporary file of %s: %s" % (self.module_name, exc))
        if cleanup_warnings and isinstance(result, dict):
            result["warnings"] = list(result.get("warnings", [])) + cleanup_warnings
        return result
