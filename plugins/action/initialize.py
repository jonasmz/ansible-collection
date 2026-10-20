# SPDX-License-Identifier: MIT-0
"""Stage the collection's initialize.pl helper and invoke initialize."""

from ansible_collections.jmz.koha.plugins.plugin_utils.helper_action import HelperActionBase


class ActionModule(HelperActionBase):
    module_name = "jmz.koha.initialize"
    helper_file = "initialize.pl"
    helper_arg = "_initialize_helper"
    prefix = "initialize"
