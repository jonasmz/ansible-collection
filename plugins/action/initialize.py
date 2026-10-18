# SPDX-License-Identifier: MIT-0
"""Stage the collection's standalone Koha Perl helper and invoke initialize."""

import os
import uuid

from ansible.plugins.action import ActionBase
from ansible.errors import AnsibleActionFail


class ActionModule(ActionBase):
    TRANSFERS_FILES = True

    def run(self, tmp=None, task_vars=None):
        result = super().run(tmp, task_vars)
        staged = None
        try:
            # ``_find_needle`` searches playbook/role paths. The helper is
            # shipped with the collection itself, so resolve it relative to
            # this action plugin on the controller instead.
            collection_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            source = os.path.join(collection_root, "files", "initialize.pl")
            if not os.path.isfile(source):
                raise AnsibleActionFail("The collection helper files/initialize.pl is missing: %s" % source)
            # The instance user must traverse the staging directory to run
            # koha-shell. Ansible's normal remote_tmp parent is often mode
            # 0700, so create this unique directory directly below shared /tmp.
            staged_path = "/tmp/ansible-koha-initialize-%s" % uuid.uuid4().hex
            staging_owner = task_vars.get("ansible_user") or self._play_context.remote_user
            if not staging_owner:
                raise AnsibleActionFail("Cannot determine the SSH user that must own the temporary staging directory")
            directory_result = self._execute_module(
                module_name="ansible.builtin.file",
                module_args={"path": staged_path, "mode": "0711", "owner": staging_owner, "state": "directory"},
                task_vars=task_vars,
            )
            if directory_result.get("failed"):
                return directory_result
            staged = staged_path
            remote_file = staged + "/initialize.pl"
            self._transfer_file(source, remote_file)

            # The helper contains no credentials. koha-shell changes to the
            # instance account, so make only this temporary directory readable
            # and traverseable, then remove it in the finally block.
            file_result = self._execute_module(
                module_name="ansible.builtin.file",
                module_args={"path": remote_file, "mode": "0644", "state": "file"},
                task_vars=task_vars,
            )
            if file_result.get("failed"):
                return file_result
            args = dict(self._task.args)
            args["_initialize_helper"] = remote_file
            return self._execute_module(
                module_name="jmz.koha.initialize",
                module_args=args,
                task_vars=task_vars,
                tmp=tmp,
            )
        except AnsibleActionFail:
            raise
        except Exception as exc:
            raise AnsibleActionFail("Unable to stage or run the Koha initialize helper: %s" % exc)
        finally:
            if staged:
                self._remove_tmp_path(staged, force=True)
