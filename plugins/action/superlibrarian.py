# SPDX-License-Identifier: MIT-0
"""Stage the collection's superlibrarian.pl helper and invoke superlibrarian."""

from ansible_collections.jmz.koha.plugins.plugin_utils.helper_action import HelperActionBase


class ActionModule(HelperActionBase):
    module_name = "jmz.koha.superlibrarian"
    helper_file = "superlibrarian.pl"
    helper_arg = "_superlibrarian_helper"
    prefix = "superlibrarian"
