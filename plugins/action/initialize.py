# SPDX-License-Identifier: MIT-0
"""Stage the collection's standalone Koha Perl helper and invoke initialize."""

from ansible.plugins.action import ActionBase
from ansible.errors import AnsibleActionFail


class ActionModule(ActionBase):
    TRANSFERS_FILES = True

    def run(self, tmp=None, task_vars=None):
        result = super().run(tmp, task_vars)
        staged = None
        try:
            source = self._find_needle("files", "initialize.pl")
            staged = self._make_tmp_path()
            remote_file = staged + "/initialize.pl"
            self._transfer_file(source, remote_file)

            # The helper contains no credentials. koha-shell changes to the
            # instance account, so make only this temporary directory readable
            # and traverseable, then remove it in the finally block.
            directory_result = self._execute_module(
                module_name="ansible.builtin.file",
                module_args={"path": staged, "mode": "0711", "state": "directory"},
                task_vars=task_vars,
            )
            if directory_result.get("failed"):
                return directory_result
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
