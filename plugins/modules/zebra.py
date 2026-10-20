# SPDX-License-Identifier: MIT-0
#!/usr/bin/python
"""Manage the Zebra daemon for one Koha instance."""

DOCUMENTATION = r'''
---
module: zebra
short_description: Manage the Zebra service for one Koha instance
description:
  - Uses the packaged C(koha-zebra) utility as the service management interface.
  - Running state and boot enablement are independent properties.
  - Does not rebuild indexes or manage C(koha-indexer).
version_added: "1.0.0"
author: Jonas MZ
requirements:
  - Koha package providing C(koha-zebra) and C(koha-list)
  - systemd for persistent enablement management; SysV supports lifecycle state only
options:
  instance:
    description: Existing Koha instance name.
    type: str
    required: true
  state:
    description:
      - Desired runtime state. Omitted means no runtime change; C(status) is read-only.
      - At least one of C(state) or C(enabled) is required.
    type: str
    choices: [started, stopped, restarted, status]
  enabled:
    description:
      - Desired persistent enablement of this instance's Zebra service.
      - Supported only when the instance has a systemd C(koha-zebra@.service) unit.
    type: bool
  verbose:
    description: Pass C(--verbose) to mutating C(koha-zebra) operations.
    type: bool
    default: false
  command_path:
    description: Absolute path to the C(koha-zebra) executable.
    type: path
    default: /usr/sbin/koha-zebra
'''

EXAMPLES = r'''
- name: Ensure Zebra is running for biblioteca
  jmz.koha.zebra:
    instance: biblioteca
    state: started
  become: true

- name: Enable Zebra at boot without starting it
  jmz.koha.zebra:
    instance: biblioteca
    enabled: true
  become: true

- name: Enable and start Zebra
  jmz.koha.zebra:
    instance: biblioteca
    enabled: true
    state: started
  become: true

- name: Stop Zebra, then disable it
  jmz.koha.zebra:
    instance: biblioteca
    state: stopped
    enabled: false
  become: true

- name: Restart Zebra explicitly
  jmz.koha.zebra:
    instance: biblioteca
    state: restarted
  become: true

- name: Observe Zebra
  jmz.koha.zebra:
    instance: biblioteca
    state: status
  register: zebra_status

- name: Manage several instances independently
  jmz.koha.zebra:
    instance: "{{ item }}"
    state: started
  loop: [biblioteca, archivo]
  become: true
'''

RETURN = r'''
instance:
  description: Koha instance name.
  returned: always
  type: str
backend:
  description: Detected Koha service backend, either C(systemd) or C(sysv).
  returned: always
  type: str
state:
  description: Final normalized runtime state, C(started) or C(stopped).
  returned: always
  type: str
previous_state:
  description: Normalized runtime state before this invocation.
  returned: always
  type: str
enabled:
  description: Final enablement boolean when systemd reports enabled or disabled; otherwise null.
  returned: always
  type: bool
previous_enabled:
  description: Previous enablement boolean when determinable; otherwise null.
  returned: always
  type: bool
enablement_state:
  description: Raw systemd UnitFileState such as enabled, disabled, masked, static, or unknown.
  returned: always
  type: str
actions:
  description: Operations executed, or planned in check mode, in execution order.
  returned: always
  type: list
  elements: str
actions_status:
  description: Whether actions are planned, executed, attempted before failure, or absent.
  returned: always
  type: str
  sample: planned
msg:
  description: Human-readable outcome.
  returned: always
  type: str
diagnostics:
  description: Bounded stdout, stderr, and return-code information for relevant commands.
  returned: always
  type: list
  elements: dict
'''

import os
import re

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import choice_normalizer


INSTANCE_RE = re.compile(r"^[a-z][a-z0-9-]{0,10}$")
UNIT_NAME = "koha-zebra@%s.service"
OUTPUT_LIMIT = 2000


class ZebraError(Exception):
    """An invalid or uninterpretable Zebra state or operation."""


def _bounded(value):
    """Keep command output useful without returning unbounded diagnostics."""
    return (value or "")[:OUTPUT_LIMIT]


def _permission_hint(message):
    lowered = message.lower()
    if "permission denied" in lowered or "operation not permitted" in lowered or "must be root" in lowered:
        return "%s (root privileges may be required; run the task with become: true)" % message
    return message


def _run(module, argv, diagnostics, operation):
    rc, stdout, stderr = module.run_command(argv)
    record = dict(operation=operation, command=argv, rc=rc,
                  stdout=_bounded(stdout), stderr=_bounded(stderr))
    diagnostics.append(record)
    return rc, stdout or "", stderr or ""


def _validate_instance(module, instance, diagnostics):
    if not isinstance(instance, str) or not INSTANCE_RE.fullmatch(instance):
        raise ZebraError("instance must be 1-11 lowercase letters, digits, or hyphens, starting with a letter")
    instance_dir = "/etc/koha/sites/%s" % instance
    if not os.path.isdir(instance_dir):
        raise ZebraError("Koha instance %s does not exist (%s is missing)" % (instance, instance_dir))
    koha_list = module.get_bin_path("koha-list", required=False)
    if not koha_list:
        raise ZebraError("koha-list was not found; cannot verify that instance %s exists" % instance)
    rc, stdout, stderr = _run(module, [koha_list], diagnostics, "verify_instance")
    if rc != 0:
        raise ZebraError("koha-list failed while verifying instance %s (rc=%s): %s" %
                         (instance, rc, _bounded(stderr or stdout).strip()))
    if instance not in stdout.splitlines():
        raise ZebraError("Koha instance %s is not listed by koha-list" % instance)


def _find_program(module, path, name):
    if path == "/usr/sbin/koha-zebra" and name == "koha-zebra":
        binary = module.get_bin_path(name, required=False)
        if not binary:
            raise ZebraError("koha-zebra was not found on the managed host")
        return binary
    if not os.path.isfile(path) or not os.access(path, os.X_OK):
        raise ZebraError("%s is missing or not executable: %s" % (name, path))
    return path


def _detect_backend(module, instance, systemctl, diagnostics):
    """Treat a loaded instance-specific unit as proof of the Koha systemd backend."""
    if not systemctl:
        return "sysv"
    unit = UNIT_NAME % instance
    rc, stdout, stderr = _run(module, [systemctl, "show", unit, "--property=LoadState", "--value"],
                              diagnostics, "detect_backend")
    load_state = stdout.strip().splitlines()[0] if stdout.strip() else ""
    if rc == 0 and load_state in ("loaded", "masked"):
        return "systemd"
    if rc == 0 and load_state == "not-found":
        return "sysv"
    # systemctl itself can exist on a non-systemd host. A not-found result above
    # also permits SysV Koha installs on systemd hosts that lack Koha unit files.
    if not os.path.isdir("/run/systemd/system"):
        return "sysv"
    raise ZebraError("Unable to identify Koha service backend for %s (systemctl rc=%s, LoadState=%s): %s" %
                     (instance, rc, load_state or "unknown", _bounded(stderr).strip()))


def _parse_sysv_status(instance, rc, stdout, stderr):
    text = "%s\n%s" % (stdout, stderr)
    lowered = text.lower()
    escaped = re.escape(instance.lower())
    if re.search(r"active:\s+active\s*\(running\)", lowered):
        return "started"
    if re.search(r"active:\s+inactive\s*\(dead\)", lowered):
        return "stopped"
    if re.search(r"zebra[^\n]*running[^\n]*\b%s\b|\brunning\s+for\s+%s\b" % (escaped, escaped), lowered):
        return "started"
    if re.search(r"zebra[^\n]*(not running|stopped)[^\n]*\b%s\b|\bnot running\s+for\s+%s\b" %
                 (escaped, escaped), lowered):
        return "stopped"
    if rc == 0 and re.search(r"\bactive\b", lowered) and "inactive" not in lowered:
        return "started"
    message = "Unable to determine Zebra state for %s from koha-zebra --status (rc=%s): %s" % \
              (instance, rc, _bounded(text).strip() or "no status output")
    raise ZebraError(_permission_hint(message))


def _inspect_runtime(module, binary, backend, instance, systemctl, diagnostics):
    if backend == "systemd":
        unit = UNIT_NAME % instance
        rc, stdout, stderr = _run(module, [systemctl, "show", unit, "--property=ActiveState", "--value"],
                                  diagnostics, "inspect_runtime")
        active = stdout.strip().splitlines()[0] if stdout.strip() else ""
        if rc == 0 and active == "active":
            return "started"
        if rc == 0 and active in ("inactive", "failed"):
            return "stopped"
        if rc != 0:
            raise ZebraError(_permission_hint("Unable to query %s runtime state (rc=%s): %s" %
                                               (unit, rc, _bounded(stderr or stdout).strip())))
        raise ZebraError("Unrecognized systemd ActiveState for %s: %s" % (unit, active or "unknown"))
    rc, stdout, stderr = _run(module, [binary, "--status", instance], diagnostics, "inspect_runtime")
    return _parse_sysv_status(instance, rc, stdout, stderr)


def _inspect_enabled(module, backend, instance, systemctl, diagnostics):
    if backend != "systemd":
        return None, "unsupported"
    unit = UNIT_NAME % instance
    rc, stdout, stderr = _run(module, [systemctl, "is-enabled", unit], diagnostics, "inspect_enabled")
    state = stdout.strip().splitlines()[0] if stdout.strip() else stderr.strip().splitlines()[0] if stderr.strip() else "unknown"
    if state == "enabled":
        return True, state
    if state == "disabled":
        return False, state
    if state in ("masked", "static", "indirect", "generated", "transient", "alias", "linked", "linked-runtime", "masked-runtime", "enabled-runtime", "disabled-runtime"):
        return None, state
    if rc != 0 and state in ("not-found", "not-found."):
        return None, "not-found"
    if rc == 0:
        return None, state
    raise ZebraError(_permission_hint("Unable to determine systemd enablement for %s (rc=%s): %s" %
                                      (unit, rc, _bounded(stderr or stdout).strip() or state)))


def _change_plan(state, enabled, runtime, enabled_value):
    actions = []
    # Deterministic order: enable before start; stop before disable.
    if enabled is True and enabled_value is False:
        actions.append("enable")
    if state == "restarted":
        actions.append("restart")
    elif state == "started" and runtime == "stopped":
        actions.append("start")
    elif state == "stopped" and runtime == "started":
        actions.append("stop")
    if enabled is False and enabled_value is True:
        actions.append("disable")
    return actions


def _run_action(module, binary, operation, instance, verbose, diagnostics):
    argv = [binary]
    if verbose:
        argv.append("--verbose")
    argv.append("--%s" % operation)
    argv.append(instance)
    rc, stdout, stderr = _run(module, argv, diagnostics, operation)
    if rc != 0:
        raise ZebraError(_permission_hint("koha-zebra --%s failed for %s (rc=%s): %s" %
                                          (operation, instance, rc, _bounded(stderr or stdout).strip())))


def main():
    module = AnsibleModule(
        argument_spec=dict(
            instance=dict(type="str", required=True),
            state=dict(type=choice_normalizer(["started", "stopped", "restarted", "status"]), choices=["started", "stopped", "restarted", "status"]),
            enabled=dict(type="bool"),
            verbose=dict(type="bool", default=False),
            command_path=dict(type="path", default="/usr/sbin/koha-zebra"),
        ),
        supports_check_mode=True,
    )
    instance = module.params["instance"]
    desired_state = module.params.get("state")
    desired_enabled = module.params.get("enabled")
    if desired_state is None and desired_enabled is None:
        module.fail_json(msg="at least one of state or enabled must be specified", instance=instance)
    if desired_state == "status" and desired_enabled is not None:
        module.fail_json(msg="state=status is read-only and cannot be combined with enabled", instance=instance)

    diagnostics = []
    actions = []
    previous_state = None
    previous_enabled = None
    enablement_state = "unknown"
    changed_any = False
    try:
        _validate_instance(module, instance, diagnostics)
        binary = _find_program(module, module.params["command_path"], "koha-zebra")
        systemctl = module.get_bin_path("systemctl", required=False)
        backend = _detect_backend(module, instance, systemctl, diagnostics)
        if desired_enabled is not None and backend != "systemd":
            raise ZebraError(
                "Persistent Zebra enablement is unsupported by the SysV backend for %s; "
                "omit enabled and request state=started or state=stopped. SysV startup is "
                "managed by koha-common for enabled Koha instances" % instance
            )
        if (desired_state in ("started", "stopped", "restarted") or desired_enabled is not None) and os.geteuid() != 0:
            raise ZebraError("root privileges are required to change Zebra; run this task with become: true")

        previous_state = _inspect_runtime(module, binary, backend, instance, systemctl, diagnostics)
        previous_enabled, enablement_state = _inspect_enabled(module, backend, instance, systemctl, diagnostics)
        if desired_enabled is not None and enablement_state not in ("enabled", "disabled"):
            raise ZebraError("Cannot set enabled=%s for Zebra unit %s with systemd UnitFileState=%s" %
                             (desired_enabled, UNIT_NAME % instance, enablement_state))
        planned = _change_plan(desired_state, desired_enabled, previous_state, previous_enabled)
        if enablement_state == "masked" and ("start" in planned or "restart" in planned):
            raise ZebraError("Cannot start masked Zebra systemd unit %s; unmask it before requesting state=%s" %
                             (UNIT_NAME % instance, desired_state))
        if module.check_mode:
            actions = planned
            final_state = previous_state
            final_enabled = previous_enabled
            if "start" in planned or "restart" in planned:
                final_state = "started"
            elif "stop" in planned:
                final_state = "stopped"
            if "enable" in planned:
                final_enabled = True
                enablement_state = "enabled (planned)"
            if "disable" in planned:
                final_enabled = False
                enablement_state = "disabled (planned)"
            module.exit_json(changed=bool(planned), instance=instance, backend=backend,
                             state=final_state, previous_state=previous_state,
                             enabled=final_enabled, previous_enabled=previous_enabled,
                             enablement_state=enablement_state, actions=actions, actions_status="planned" if planned else "none",
                             msg="Zebra changes planned" if planned else "Zebra already matches the requested state",
                             diagnostics=diagnostics)

        # Do not claim or execute changes until there is a reliable pre-state.
        for operation in planned:
            actions.append(operation)
            try:
                _run_action(module, binary, operation, instance, module.params["verbose"], diagnostics)
            except ZebraError:
                # The utility can fail after it has already affected the service.
                # Best-effort observation lets fail_json report that partial change.
                try:
                    if operation in ("start", "stop", "restart"):
                        changed_any = changed_any or (
                            _inspect_runtime(module, binary, backend, instance, systemctl, diagnostics) != previous_state
                        )
                    else:
                        observed_enabled, _observed_enablement_state = _inspect_enabled(
                            module, backend, instance, systemctl, diagnostics)
                        changed_any = changed_any or observed_enabled != previous_enabled
                except ZebraError:
                    pass
                raise
            changed_any = True
            # Verify each dimension immediately; a later action must not hide a failed one.
            if operation in ("start", "stop", "restart"):
                actual = _inspect_runtime(module, binary, backend, instance, systemctl, diagnostics)
                if operation in ("start", "restart") and actual != "started":
                    raise ZebraError("Zebra did not reach started state after --%s for %s" % (operation, instance))
                if operation == "stop" and actual != "stopped":
                    raise ZebraError("Zebra did not reach stopped state after --stop for %s" % instance)
            else:
                actual_enabled, actual_state = _inspect_enabled(module, backend, instance, systemctl, diagnostics)
                if actual_enabled != (operation == "enable") or actual_state != ("enabled" if operation == "enable" else "disabled"):
                    raise ZebraError("Zebra systemd enablement did not reach the requested state after --%s for %s" %
                                     (operation, instance))

        final_state = _inspect_runtime(module, binary, backend, instance, systemctl, diagnostics)
        final_enabled, enablement_state = _inspect_enabled(module, backend, instance, systemctl, diagnostics)
        if desired_state == "started" and final_state != "started":
            raise ZebraError("Zebra postcondition failed: expected started, observed %s" % final_state)
        if desired_state == "stopped" and final_state != "stopped":
            raise ZebraError("Zebra postcondition failed: expected stopped, observed %s" % final_state)
        if desired_enabled is not None and final_enabled is not desired_enabled:
            raise ZebraError("Zebra enablement postcondition failed: expected %s, observed %s" %
                             (desired_enabled, enablement_state))
        module.exit_json(changed=changed_any, instance=instance, backend=backend,
                         state=final_state, previous_state=previous_state,
                         enabled=final_enabled, previous_enabled=previous_enabled,
                         enablement_state=enablement_state, actions=actions, actions_status="executed" if actions else "none",
                         msg="Zebra operations completed" if changed_any else "Zebra already matches the requested state",
                         diagnostics=diagnostics)
    except ZebraError as exc:
        module.fail_json(msg=str(exc), changed=changed_any, instance=instance,
                         backend=locals().get("backend", "unknown"),
                         state=locals().get("final_state", previous_state), previous_state=previous_state,
                         enabled=locals().get("final_enabled", previous_enabled), previous_enabled=previous_enabled,
                         enablement_state=enablement_state, actions=actions,
                         actions_status="attempted" if actions else "none", diagnostics=diagnostics)


if __name__ == "__main__":
    main()
