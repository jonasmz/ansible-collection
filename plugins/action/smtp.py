# SPDX-License-Identifier: MIT-0
"""Stage the collection's smtp.pl helper and invoke smtp."""

from ansible_collections.jmz.koha.plugins.plugin_utils.helper_action import HelperActionBase


class ActionModule(HelperActionBase):
    module_name = "jmz.koha.smtp"
    helper_file = "smtp.pl"
    helper_arg = "_smtp_helper"
    prefix = "smtp"
