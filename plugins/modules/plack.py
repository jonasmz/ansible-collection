# SPDX-License-Identifier: MIT-0
#!/usr/bin/python
"""Manage the Plack daemon for one Koha instance."""

DOCUMENTATION = r'''
---
module: plack
short_description: Manage a Koha instance's Plack daemon and configuration
description:
  - Uses the packaged C(koha-plack) utility for lifecycle and enablement operations.
  - C(enabled) controls Koha's Apache Plack configuration and systemd boot enablement; it does not start or stop the daemon.
  - C(state) controls the running daemon independently.
version_added: "1.1.0"
author: Jonas MZ
requirements:
  - koha-plack installed on the managed host
options:
  instance:
    description: Koha instance identifier.
    type: str
    required: true
  state:
    description: Desired daemon state. Omitted means observe only.
    type: str
    choices: [started, stopped, restarted, reloaded, status]
  enabled:
    description: Whether Plack should be enabled in Koha's instance Apache configuration.
    type: bool
'''

EXAMPLES = r'''
- name: Start Plack
  jmz.koha.plack:
    instance: biblioteca
    state: started
  become: true

- name: Enable Plack without starting it
  jmz.koha.plack:
    instance: biblioteca
    enabled: true
  become: true

- name: Enable and start Plack
  jmz.koha.plack:
    instance: biblioteca
    enabled: true
    state: started
  become: true

- name: Gracefully reload Plack
  jmz.koha.plack:
    instance: biblioteca
    state: reloaded
  become: true

- name: Observe Plack state
  jmz.koha.plack:
    instance: biblioteca
    state: status

- name: Manage several instances
  jmz.koha.plack:
    instance: "{{ item }}"
    state: started
    enabled: true
  loop:
    - biblioteca
    - archivo
  become: true
'''

RETURN = r'''
instance:
  description: Koha instance identifier.
  returned: always
  type: str
running:
  description: Whether the Plack daemon is running.
  returned: always
  type: bool
enabled:
  description: Whether Plack is enabled in the Koha instance configuration.
  returned: always
  type: bool
state:
  description: Observed daemon state.
  returned: always
  type: str
  sample: running
actions:
  description: Lifecycle or configuration operations executed by this invocation.
  returned: always
  type: list
stdout:
  description: Relevant command output.
  returned: when a command was executed
  type: str
stderr:
  description: Relevant command diagnostics.
  returned: when a command was executed
  type: str
rc:
  description: Last command return code.
  returned: when a command was executed
  type: int
'''

import os
import re

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import choice_normalizer


NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,10}$")
OPAC_INCLUDE = re.compile(r"^\s*Include /etc/koha/apache-shared-opac-plack\.conf\s*$")
INTRA_INCLUDE = re.compile(r"^\s*Include /etc/koha/apache-shared-intranet-plack\.conf\s*$")


class PlackError(Exception):
    """An invalid or uninterpretable Koha Plack state."""


def _active_include(lines, pattern):
    return any(pattern.match(line) for line in lines)


def inspect_enabled(instance):
    """Read the same Apache includes inspected by Koha's is_plack_enabled()."""
    config = "/etc/apache2/sites-available/%s.conf" % instance
    if not os.path.isfile(config):
        # Koha supports the extensionless site file as a legacy alternative.
        config = "/etc/apache2/sites-available/%s" % instance
    if not os.path.isfile(config):
        raise PlackError("Koha Apache configuration for instance %s was not found" % instance)
    try:
        with open(config, "r", encoding="utf-8") as stream:
            lines = stream.readlines()
    except OSError as exc:
        raise PlackError("Unable to read Koha Apache configuration %s: %s" % (config, exc))
    opac = _active_include(lines, OPAC_INCLUDE)
    intranet = _active_include(lines, INTRA_INCLUDE)
    if opac != intranet:
        raise PlackError("Plack configuration for %s is inconsistent between OPAC and intranet" % instance)
    return opac


def inspect_running(module, binary, instance):
    """Use koha-plack's status action and accept only source-backed status results."""
    rc, stdout, stderr = module.run_command([binary, "--status", instance])
    output = "%s\n%s" % (stdout, stderr)
    normalized = output.lower()
    if rc == 0:
        if "plack running for" in normalized or re.search(r"active:\s+active \(running\)", normalized):
            return True, rc, stdout, stderr
        raise PlackError("koha-plack --status returned success but its output did not identify a running daemon")
    if rc == 3 and ("plack not running for" in normalized or "active: inactive (dead)" in normalized):
        return False, rc, stdout, stderr
    if "does not exist" in normalized or "not a koha instance" in normalized or "no such instance" in normalized:
        raise PlackError("Koha instance %s does not exist" % instance)
    raise PlackError("Unable to determine Plack status (rc=%s): %s" % (rc, output.strip()))


def _run(module, binary, operation, instance):
    rc, stdout, stderr = module.run_command([binary, "--%s" % operation, instance])
    if rc != 0:
        raise PlackError("koha-plack --%s failed for %s (rc=%s): %s" %
                         (operation, instance, rc, (stderr or stdout).strip()))
    return rc, stdout, stderr


def main():
    module = AnsibleModule(
        argument_spec=dict(
            instance=dict(type="str", required=True),
            state=dict(type=choice_normalizer(["started", "stopped", "restarted", "reloaded", "status"]), choices=["started", "stopped", "restarted", "reloaded", "status"]),
            enabled=dict(type="bool"),
        ),
        supports_check_mode=True,
    )
    instance = module.params["instance"]
    desired_state = module.params.get("state")
    desired_enabled = module.params.get("enabled")
    if not NAME_RE.fullmatch(instance):
        module.fail_json(msg="instance must be a valid Koha instance identifier (1-11 lowercase letters, digits, or hyphens; starting with a letter)", instance=instance)
    if desired_state == "status" and desired_enabled is not None:
        module.fail_json(msg="state=status is read-only and cannot be combined with enabled", instance=instance)
    binary = module.get_bin_path("koha-plack", required=False)
    if not binary:
        module.fail_json(msg="koha-plack was not found on the managed host; install the Koha package providing it", instance=instance)
    if not os.path.isfile("/etc/koha/sites/%s/koha-conf.xml" % instance):
        module.fail_json(msg="Koha instance %s does not exist (koha-conf.xml not found)" % instance, instance=instance)

    try:
        running, rc, stdout, stderr = inspect_running(module, binary, instance)
        enabled = inspect_enabled(instance)
        action_state = {
            "started": "start" if not running else None,
            "stopped": "stop" if running else None,
            "restarted": "restart",
            "reloaded": "reload",
        }.get(desired_state)
        action_enabled = None
        if desired_enabled is not None and desired_enabled != enabled:
            action_enabled = "enable" if desired_enabled else "disable"
        actions = []
        changed = False
        if action_enabled:
            if not module.check_mode:
                rc, out, err = _run(module, binary, action_enabled, instance)
                stdout += out
                stderr += err
                enabled = inspect_enabled(instance)
                if enabled != desired_enabled:
                    raise PlackError("koha-plack --%s did not produce the requested Plack configuration" % action_enabled)
            actions.append(action_enabled)
            enabled = desired_enabled
            changed = True
        if action_state:
            if not module.check_mode:
                rc, out, err = _run(module, binary, action_state, instance)
                stdout += out
                stderr += err
                running, rc, out, err = inspect_running(module, binary, instance)
                stdout += out
                stderr += err
                if action_state in ("start", "restart") and not running:
                    raise PlackError("Plack remained stopped after koha-plack --%s" % action_state)
                if action_state == "stop" and running:
                    raise PlackError("Plack remained running after koha-plack --stop")
            actions.append(action_state)
            changed = True
        module.exit_json(changed=changed, instance=instance, running=running, enabled=enabled,
                         state="running" if running else "stopped", actions=actions,
                         stdout=stdout, stderr=stderr, rc=rc)
    except PlackError as exc:
        module.fail_json(msg=str(exc), instance=instance, rc=locals().get("rc"),
                         stdout=locals().get("stdout", ""), stderr=locals().get("stderr", ""))


if __name__ == "__main__":
    main()
