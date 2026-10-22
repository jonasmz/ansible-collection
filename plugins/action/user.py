# SPDX-License-Identifier: MIT-0
"""Stage the collection's user.pl helper and invoke user."""

from ansible_collections.jmz.koha.plugins.plugin_utils.helper_action import HelperActionBase


class ActionModule(HelperActionBase):
    module_name = "jmz.koha.user"
    helper_file = "user.pl"
    helper_arg = "_user_helper"
    prefix = "user"
