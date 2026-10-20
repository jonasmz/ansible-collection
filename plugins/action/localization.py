# SPDX-License-Identifier: MIT-0
"""Stage the collection's localization.pl helper and invoke localization."""

from ansible_collections.jmz.koha.plugins.plugin_utils.helper_action import HelperActionBase


class ActionModule(HelperActionBase):
    module_name = "jmz.koha.localization"
    helper_file = "localization.pl"
    helper_arg = "_localization_helper"
    prefix = "localization"
