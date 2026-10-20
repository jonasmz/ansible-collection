# SPDX-License-Identifier: MIT-0
"""Stage the standalone Koha localization helper and invoke the module."""

import os
import uuid

from ansible.errors import AnsibleActionFail
from ansible.plugins.action import ActionBase


class ActionModule(ActionBase):
    TRANSFERS_FILES = True

    def run(self, tmp=None, task_vars=None):
        result = super().run(tmp, task_vars)
        task_vars = task_vars or {}
        staged = None
        upload_tmp = None
        try:
            collection_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            source = os.path.join(collection_root, "files", "localization.pl")
            if not os.path.isfile(source):
                raise AnsibleActionFail("The collection helper files/localization.pl is missing")
            upload_tmp = self._make_tmp_path()
            upload_file = upload_tmp + "/localization.pl"
            self._transfer_file(source, upload_file)
            staged = "/tmp/ansible-koha-localization-%s" % uuid.uuid4().hex
            directory_result = self._execute_module(
                module_name="ansible.builtin.file",
                module_args={"path": staged, "mode": "0711", "state": "directory"},
                task_vars=task_vars,
            )
            if directory_result.get("failed"):
                return directory_result
            remote_file = staged + "/localization.pl"
            copy_result = self._execute_module(
                module_name="ansible.builtin.command",
                module_args={"argv": ["/usr/bin/cp", "--", upload_file, remote_file]},
                task_vars=task_vars,
            )
            if copy_result.get("failed"):
                return copy_result
            file_result = self._execute_module(
                module_name="ansible.builtin.file",
                module_args={"path": remote_file, "mode": "0644", "state": "file"},
                task_vars=task_vars,
            )
            if file_result.get("failed"):
                return file_result
            args = dict(self._task.args)
            args["_localization_helper"] = remote_file
            return self._execute_module("jmz.koha.localization", args, task_vars=task_vars, tmp=tmp)
        except AnsibleActionFail:
            raise
        except Exception as exc:
            raise AnsibleActionFail("Unable to stage or run the Koha localization helper: %s" % exc)
        finally:
            if staged:
                try:
                    self._execute_module(
                        module_name="ansible.builtin.file",
                        module_args={"path": staged, "state": "absent"},
                        task_vars=task_vars,
                    )
                except Exception:
                    pass
            if upload_tmp:
                try:
                    self._remove_tmp_path(upload_tmp, force=True)
                except Exception:
                    pass
