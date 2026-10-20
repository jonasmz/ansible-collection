# SPDX-License-Identifier: MIT-0
#!/usr/bin/python
"""Manage the incremental Zebra indexer daemon for one Koha instance."""

DOCUMENTATION = r'''
---
module: zebra_indexer
short_description: Manage one Koha instance's incremental Zebra indexer daemon
description:
  - Uses the packaged C(koha-indexer) command for indexer lifecycle operations.
  - The indexer is separate from the Zebra server managed by C(jmz.koha.zebra).
  - Does not rebuild indexes, run batch indexing, manage Elasticsearch, or change Koha configuration.
version_added: "1.2.0"
author: Jonas MZ
requirements:
  - Debian or Ubuntu Koha package providing C(koha-indexer), C(koha-list), and Koha service helpers
  - systemd-specific Koha units for persistent enablement; SysV does not support it
options:
  instance:
    description: Existing Koha instance name.
    type: str
    required: true
  state:
    description:
      - Desired runtime state. Omitted means do not change runtime state.
      - At least one of C(state) or C(enabled) is required. C(status) is read-only.
    type: str
    choices: [started, stopped, restarted, status]
  enabled:
    description:
      - Persistent service enablement. This does not start or stop the daemon.
      - Requires a backend and installed C(koha-indexer) version that expose C(--enable) and C(--disable).
    type: bool
  quiet:
    description: Pass C(--quiet) to koha-indexer operations.
    type: bool
    default: false
  command_path:
    description: Absolute path to the C(koha-indexer) command.
    type: path
    default: /usr/sbin/koha-indexer
  verify_zebra_engine:
    description:
      - Verify the C(SearchEngine) system preference using Koha's C(koha-shell) and C(koha-preferences) utility.
      - Strictly permits starts and restarts only when the preference is C(Zebra).
      - A failed or inconclusive query is an error. Stopping and status remain available.
    type: bool
    default: false
  require_zebra_running:
    description:
      - Require the same instance's Zebra server to be active before starting or restarting this indexer.
      - This is a read-only check; Zebra is never started by this module.
    type: bool
    default: false
'''

EXAMPLES = r'''
- name: Ensure the incremental indexer is running
  jmz.koha.zebra_indexer:
    instance: biblioteca
    state: started
  become: true

- name: Stop the indexer without disabling it at boot
  jmz.koha.zebra_indexer:
    instance: biblioteca
    state: stopped
  become: true

- name: Enable at boot without starting
  jmz.koha.zebra_indexer:
    instance: biblioteca
    enabled: true
  become: true

- name: Verify Zebra engine and server before starting
  jmz.koha.zebra_indexer:
    instance: biblioteca
    state: started
    verify_zebra_engine: true
    require_zebra_running: true
  become: true

- name: Restart the indexer explicitly
  jmz.koha.zebra_indexer:
    instance: biblioteca
    state: restarted
  become: true

- name: Observe state without changing it
  jmz.koha.zebra_indexer:
    instance: biblioteca
    state: status
  register: indexer_status

- name: Preview a combined enable and start
  jmz.koha.zebra_indexer:
    instance: biblioteca
    state: started
    enabled: true
  check_mode: true
  become: true
'''

RETURN = r'''
instance:
  description: Koha instance name.
  returned: always
  type: str
backend:
  description: Koha service backend, C(systemd) or C(sysv).
  returned: always
  type: str
state:
  description: Observed normalized runtime state, C(started), C(stopped), or C(unknown).
  returned: always
  type: str
previous_state:
  description: Normalized runtime state observed before operations.
  returned: always
  type: str
enabled:
  description: Observed enablement boolean for supported enablement states, otherwise null.
  returned: always
  type: bool
previous_enabled:
  description: Enablement observed before operations, or null when unsupported or indeterminate.
  returned: always
  type: bool
search_engine:
  description: SearchEngine preference if strict verification was requested, otherwise null.
  returned: always
  type: str
zebra_running:
  description: Zebra runtime check if required, otherwise null.
  returned: always
  type: bool
actions:
  description: Operations actually attempted in order.
  returned: always
  type: list
  elements: str
planned_actions:
  description: Operations that check mode predicts would run.
  returned: always
  type: list
  elements: str
enablement_state:
  description: Raw systemd UnitFileState or C(unsupported) for SysV.
  returned: always
  type: str
diagnostics:
  description: Bounded command diagnostics with operation, return code, stdout, and stderr.
  returned: always
  type: list
  elements: dict
msg:
  description: Human-readable result.
  returned: always
  type: str
'''

import os
import re
import shlex
import time

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import choice_normalizer


INSTANCE_RE = re.compile(r"^[a-z][a-z0-9-]{0,10}$")
INDEXER_UNIT = "koha-indexer@%s.service"
ZEBRA_UNIT = "koha-zebra@%s.service"
OUTPUT_LIMIT = 2000
VERIFY_TIMEOUT = 5.0


class IndexerError(Exception):
    """An invalid, unsafe, or uninterpretable indexer operation."""


def _bounded(value):
    return (value or "")[:OUTPUT_LIMIT]


def _record(module, argv, diagnostics, operation):
    try:
        rc, stdout, stderr = module.run_command(argv)
    except OSError as exc:
        diagnostics.append(dict(operation=operation, command=argv, rc=None, stdout="", stderr=_bounded(str(exc))))
        raise IndexerError("Unable to execute %s: %s" % (argv[0], exc))
    diagnostics.append(dict(operation=operation, command=argv, rc=rc,
                            stdout=_bounded(stdout), stderr=_bounded(stderr)))
    return rc, stdout or "", stderr or ""


def _validate_instance(module, instance, diagnostics):
    if not isinstance(instance, str) or not INSTANCE_RE.fullmatch(instance):
        raise IndexerError("instance must be 1-11 lowercase letters, digits, or hyphens, starting with a letter")
    config = "/etc/koha/sites/%s/koha-conf.xml" % instance
    if not os.path.isdir("/etc/koha/sites/%s" % instance) or not os.path.isfile(config):
        raise IndexerError("Koha instance %s does not exist or its koha-conf.xml is missing" % instance)
    koha_list = module.get_bin_path("koha-list", required=False)
    if not koha_list:
        raise IndexerError("koha-list was not found; cannot independently verify instance %s" % instance)
    rc, stdout, stderr = _record(module, [koha_list], diagnostics, "verify_instance")
    if rc != 0 or instance not in stdout.splitlines():
        raise IndexerError("koha-list did not confirm instance %s (rc=%s): %s" %
                           (instance, rc, _bounded(stderr or stdout).strip()))


def _find_command(module, path, command):
    if path == "/usr/sbin/koha-indexer":
        resolved = module.get_bin_path("koha-indexer", required=False)
        if not resolved:
            raise IndexerError("koha-indexer was not found on the managed host")
        path = resolved
    if not os.path.isabs(path) or not os.path.isfile(path) or not os.access(path, os.X_OK):
        raise IndexerError("%s is missing or not executable: %s" % (command, path))
    return path


def _detect_backend(module, instance, systemctl, diagnostics):
    """Match Koha's koha_init_backend: systemd PID 1 plus installed Koha units."""
    if not os.path.isdir("/run/systemd/system"):
        return "sysv"
    if not systemctl:
        return "sysv"
    for base in ("/lib/systemd/system", "/usr/lib/systemd/system", "/etc/systemd/system"):
        if any(os.path.isfile(os.path.join(base, "koha-%s@.service" % service))
               for service in ("indexer", "zebra", "plack")):
            return "systemd"
    # Some Koha releases install common service templates and instance-specific units.
    rc, stdout, stderr = _record(module, [systemctl, "show", INDEXER_UNIT % instance,
                                          "--property=LoadState", "--value"], diagnostics, "detect_backend")
    load_state = stdout.strip().splitlines()[0] if stdout.strip() else ""
    if rc == 0 and load_state in ("loaded", "masked"):
        return "systemd"
    if rc == 0 and load_state in ("not-found", ""):
        return "sysv"
    raise IndexerError("Unable to detect Koha service backend for %s (systemctl rc=%s, LoadState=%s): %s" %
                       (instance, rc, load_state or "unknown", _bounded(stderr).strip()))


def _inspect_runtime(module, binary, backend, instance, systemctl, quiet, diagnostics):
    if backend == "systemd":
        unit = INDEXER_UNIT % instance
        load_rc, load_out, load_err = _record(module, [systemctl, "show", unit,
                                                       "--property=LoadState", "--value"],
                                             diagnostics, "verify_indexer_unit")
        load_state = load_out.strip().splitlines()[0] if load_out.strip() else ""
        if load_rc != 0 or load_state not in ("loaded", "masked"):
            raise IndexerError("Koha indexer unit %s is unavailable (LoadState=%s, rc=%s): %s" %
                               (unit, load_state or "unknown", load_rc, _bounded(load_err or load_out).strip()))
        rc, stdout, stderr = _record(module, [systemctl, "show", INDEXER_UNIT % instance,
                                              "--property=ActiveState", "--value"], diagnostics, "inspect_runtime")
        value = stdout.strip().splitlines()[0] if stdout.strip() else ""
        if rc != 0:
            raise IndexerError("Unable to query indexer state for %s (rc=%s): %s" %
                               (instance, rc, _bounded(stderr or stdout).strip()))
        if value == "active" or value in ("activating", "deactivating"):
            return "started" if value == "active" else "unknown"
        if value in ("inactive", "failed"):
            return "stopped"
        raise IndexerError("Unrecognized systemd ActiveState for %s: %s" % (instance, value or "unknown"))
    argv = [binary, "--status"]
    if quiet:
        argv.append("--quiet")
    argv.append(instance)
    rc, stdout, stderr = _record(module, argv, diagnostics, "inspect_runtime")
    text = (stdout + "\n" + stderr).lower()
    escaped = re.escape(instance.lower())
    if re.search(r"indexer[^\n]*running[^\n]*\b%s\b|\brunning for instance\s+%s\b" % (escaped, escaped), text):
        return "started"
    if re.search(r"indexer[^\n]*(not running|stopped)[^\n]*\b%s\b|\bnot running for instance\s+%s\b" %
                 (escaped, escaped), text):
        return "stopped"
    raise IndexerError("Unable to determine indexer status for %s (rc=%s): %s" %
                       (instance, rc, _bounded(text).strip() or "no status output"))


def _inspect_enabled(module, backend, instance, systemctl, diagnostics):
    if backend != "systemd":
        return None, "unsupported"
    unit = INDEXER_UNIT % instance
    rc, stdout, stderr = _record(module, [systemctl, "is-enabled", unit], diagnostics, "inspect_enabled")
    state = (stdout or stderr).strip().splitlines()[0] if (stdout or stderr).strip() else "unknown"
    if state == "enabled":
        return True, state
    if state == "disabled":
        return False, state
    known = ("static", "indirect", "masked", "masked-runtime", "enabled-runtime", "disabled-runtime",
             "generated", "transient", "alias", "linked", "linked-runtime", "not-found")
    if state in known:
        return None, state
    if rc == 0:
        return None, state
    raise IndexerError("Unable to determine indexer enablement for %s (rc=%s): %s" %
                       (unit, rc, _bounded(stderr or stdout).strip() or state))


def _check_option_support(module, binary, wanted, quiet, diagnostics):
    argv = [binary, "--help"]
    if quiet:
        argv.append("--quiet")
    rc, stdout, stderr = _record(module, argv, diagnostics, "inspect_cli_options")
    help_text = stdout + "\n" + stderr
    if rc != 0 or not re.search(r"(?m)(?:^|\s)%s(?:\s|$)" % re.escape(wanted), help_text):
        raise IndexerError("Installed koha-indexer does not advertise %s in --help; enablement is unsupported" % wanted)


def _search_engine(module, instance, diagnostics):
    koha_shell = module.get_bin_path("koha-shell", required=False)
    if not koha_shell:
        raise IndexerError("Cannot verify SearchEngine: koha-shell was not found")
    pref = "/usr/share/koha/bin/admin/koha-preferences"
    if not os.path.isfile(pref) or not os.access(pref, os.X_OK):
        raise IndexerError("Cannot verify SearchEngine: Koha koha-preferences utility is missing or not executable")
    # The instance is regex-restricted above; pass the entire -c payload as one argv item.
    script = "%s get SearchEngine 2>/dev/null" % pref
    rc, stdout, stderr = _record(module, [koha_shell, instance, "-c", script], diagnostics, "inspect_search_engine")
    value = stdout.strip()
    if rc != 0 or value not in ("Zebra", "Elasticsearch"):
        raise IndexerError("Unable to reliably read SearchEngine for %s (rc=%s): %s" %
                           (instance, rc, _bounded(stderr or stdout).strip() or "unrecognized value"))
    return value


def _alternate_indexer():
    """Read only a simple static assignment; never source a root-owned shell file."""
    path = "/etc/default/koha-common"
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as stream:
            lines = stream.readlines()
    except OSError as exc:
        raise IndexerError("Unable to inspect /etc/default/koha-common safely: %s" % exc)
    value = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "ALTERNATE_INDEXER_DAEMON" not in stripped:
            continue
        match = re.fullmatch(r"(?:export\s+)?ALTERNATE_INDEXER_DAEMON\s*=\s*(.*?)\s*", stripped)
        if not match:
            raise IndexerError("ALTERNATE_INDEXER_DAEMON is configured dynamically; refusing mutating indexer actions")
        raw = match.group(1)
        if any(token in raw for token in ("$", "`", ";", "&", "|", ">", "<", "\n")):
            raise IndexerError("ALTERNATE_INDEXER_DAEMON uses shell expansion; refusing mutating indexer actions")
        try:
            words = shlex.split(raw, comments=False, posix=True)
        except ValueError:
            raise IndexerError("ALTERNATE_INDEXER_DAEMON cannot be parsed safely")
        if len(words) > 1:
            raise IndexerError("ALTERNATE_INDEXER_DAEMON is not a single static executable path")
        value = words[0] if words else ""
    return value or None


def _zebra_running(module, instance, zebra_binary, backend, systemctl, quiet, diagnostics):
    if backend == "systemd":
        unit = ZEBRA_UNIT % instance
        load_rc, load_out, load_err = _record(module, [systemctl, "show", unit,
                                                       "--property=LoadState", "--value"],
                                             diagnostics, "verify_zebra_unit")
        load_state = load_out.strip().splitlines()[0] if load_out.strip() else ""
        if load_rc != 0 or load_state not in ("loaded", "masked"):
            raise IndexerError("Koha Zebra unit %s is unavailable (LoadState=%s, rc=%s): %s" %
                               (unit, load_state or "unknown", load_rc, _bounded(load_err or load_out).strip()))
        rc, stdout, stderr = _record(module, [systemctl, "show", ZEBRA_UNIT % instance,
                                              "--property=ActiveState", "--value"], diagnostics, "inspect_zebra")
        value = stdout.strip().splitlines()[0] if stdout.strip() else ""
        if rc != 0 or value not in ("active", "inactive", "failed"):
            raise IndexerError("Unable to determine Zebra service state for %s (rc=%s): %s" %
                               (instance, rc, _bounded(stderr or stdout).strip() or value or "unknown"))
        return value == "active"
    argv = [zebra_binary, "--status"]
    if quiet:
        argv.append("--quiet")
    argv.append(instance)
    rc, stdout, stderr = _record(module, argv, diagnostics, "inspect_zebra")
    text = (stdout + "\n" + stderr).lower()
    if re.search(r"zebra[^\n]*running[^\n]*\b%s\b|\brunning for instance\s+%s\b" %
                 (re.escape(instance), re.escape(instance)), text):
        return True
    if re.search(r"zebra[^\n]*(not running|stopped)[^\n]*\b%s\b|\bnot running for instance\s+%s\b" %
                 (re.escape(instance), re.escape(instance)), text):
        return False
    raise IndexerError("Unable to determine Zebra status for %s: %s" %
                       (instance, _bounded(text).strip() or "no status output"))


def _plan(state, desired_enabled, current_state, current_enabled):
    actions = []
    if desired_enabled is True and current_enabled is False:
        actions.append("enable")
    if state == "restarted":
        actions.append("restart")
    elif state == "started" and current_state == "stopped":
        actions.append("start")
    elif state == "stopped" and current_state == "started":
        actions.append("stop")
    if desired_enabled is False and current_enabled is True:
        actions.append("disable")
    return actions


def _run_action(module, binary, operation, instance, quiet, diagnostics):
    argv = [binary, "--%s" % operation]
    if quiet:
        argv.append("--quiet")
    argv.append(instance)
    rc, stdout, stderr = _record(module, argv, diagnostics, operation)
    if rc != 0:
        raise IndexerError("koha-indexer --%s failed for %s (rc=%s): %s" %
                           (operation, instance, rc, _bounded(stderr or stdout).strip()))


def _wait_runtime(module, binary, backend, instance, systemctl, quiet, expected, diagnostics):
    deadline = time.monotonic() + VERIFY_TIMEOUT
    last = "unknown"
    while True:
        last = _inspect_runtime(module, binary, backend, instance, systemctl, quiet, diagnostics)
        if last == expected:
            return last
        if time.monotonic() >= deadline:
            return last
        time.sleep(0.25)


def main():
    module = AnsibleModule(argument_spec=dict(
        instance=dict(type="str", required=True),
        state=dict(type=choice_normalizer(["started", "stopped", "restarted", "status"]), choices=["started", "stopped", "restarted", "status"]),
        enabled=dict(type="bool"), quiet=dict(type="bool", default=False),
        command_path=dict(type="path", default="/usr/sbin/koha-indexer"),
        verify_zebra_engine=dict(type="bool", default=False),
        require_zebra_running=dict(type="bool", default=False),
    ), supports_check_mode=True)
    p = module.params
    instance, desired_state, desired_enabled = p["instance"], p.get("state"), p.get("enabled")
    if desired_state is None and desired_enabled is None:
        module.fail_json(msg="at least one of state or enabled must be specified", instance=instance)
    if desired_state == "status" and desired_enabled is not None:
        module.fail_json(msg="state=status is read-only and cannot be combined with enabled", instance=instance)

    diagnostics, actions = [], []
    previous_state = final_state = None
    previous_enabled = final_enabled = None
    backend, enablement_state = "unknown", "unknown"
    search_engine = zebra_running = None
    changed_any = False
    try:
        _validate_instance(module, instance, diagnostics)
        binary = _find_command(module, p["command_path"], "koha-indexer")
        systemctl = module.get_bin_path("systemctl", required=False)
        backend = _detect_backend(module, instance, systemctl, diagnostics)
        if desired_enabled is not None:
            if backend != "systemd":
                raise IndexerError("Persistent indexer enablement is unsupported by the SysV backend for %s" % instance)
            _check_option_support(module, binary, "--enable" if desired_enabled else "--disable", p["quiet"], diagnostics)
        if (desired_state in ("started", "stopped", "restarted") or desired_enabled is not None) and os.geteuid() != 0:
            raise IndexerError("root privileges are required to modify the indexer; run this task with become: true")
        previous_state = _inspect_runtime(module, binary, backend, instance, systemctl, p["quiet"], diagnostics)
        if previous_state == "unknown" and desired_state in ("started", "stopped", "restarted"):
            raise IndexerError("Indexer state for %s is transitional/unknown; refusing to plan a modification" % instance)
        previous_enabled, enablement_state = _inspect_enabled(module, backend, instance, systemctl, diagnostics)
        if desired_enabled is not None and enablement_state not in ("enabled", "disabled"):
            raise IndexerError("Cannot set enabled=%s for %s with systemd UnitFileState=%s" %
                               (desired_enabled, INDEXER_UNIT % instance, enablement_state))
        if enablement_state in ("masked", "masked-runtime") and desired_state in ("started", "restarted"):
            raise IndexerError("Cannot start masked indexer unit %s; unmask it before requesting state=%s" %
                               (INDEXER_UNIT % instance, desired_state))
        if p["verify_zebra_engine"]:
            search_engine = _search_engine(module, instance, diagnostics)
            if desired_state in ("started", "restarted") and search_engine != "Zebra":
                raise IndexerError("Refusing to start/restart the Zebra indexer for %s: SearchEngine is %s" %
                                   (instance, search_engine))
        planned = _plan(desired_state, desired_enabled, previous_state, previous_enabled)
        if planned:
            alternate = _alternate_indexer()
            if alternate:
                raise IndexerError("Refusing mutating indexer actions for %s: ALTERNATE_INDEXER_DAEMON selects %s, "
                                   "which may not be the Zebra incremental indexer" % (instance, alternate))
        if p["require_zebra_running"] and desired_state in ("started", "restarted"):
            zebra_binary = module.get_bin_path("koha-zebra", required=False)
            if not zebra_binary:
                raise IndexerError("Cannot verify Zebra dependency: koha-zebra was not found")
            zebra_running = _zebra_running(module, instance, zebra_binary, backend, systemctl, p["quiet"], diagnostics)
            if not zebra_running:
                raise IndexerError("Zebra is stopped for %s; start it with jmz.koha.zebra before starting the indexer" % instance)

        if module.check_mode:
            # In check mode report the observed state, never the hypothetical post-state.
            module.exit_json(changed=bool(planned), instance=instance, backend=backend, state=previous_state,
                             previous_state=previous_state, enabled=previous_enabled,
                             previous_enabled=previous_enabled, enablement_state=enablement_state,
                             search_engine=search_engine, zebra_running=zebra_running,
                             actions=[], planned_actions=planned, diagnostics=diagnostics,
                             msg="Indexer operations planned" if planned else "Indexer already matches requested state")

        for operation in planned:
            actions.append(operation)
            try:
                _run_action(module, binary, operation, instance, p["quiet"], diagnostics)
            except IndexerError:
                if operation == "restart":
                    # A failed restart may still have restarted an already-active process.
                    changed_any = True
                if operation in ("start", "stop", "restart"):
                    try:
                        observed = _inspect_runtime(module, binary, backend, instance, systemctl, p["quiet"], diagnostics)
                        changed_any = changed_any or observed != previous_state
                    except IndexerError:
                        pass
                elif operation in ("enable", "disable"):
                    try:
                        observed_enabled, _ = _inspect_enabled(module, backend, instance, systemctl, diagnostics)
                        changed_any = changed_any or observed_enabled != previous_enabled
                    except IndexerError:
                        pass
                raise
            changed_any = True
            if operation in ("start", "stop", "restart"):
                expected = "stopped" if operation == "stop" else "started"
                actual = _wait_runtime(module, binary, backend, instance, systemctl, p["quiet"], expected, diagnostics)
                if actual != expected:
                    raise IndexerError("Indexer did not reach %s after --%s for %s (observed %s)" %
                                       (expected, operation, instance, actual))
            else:
                actual_enabled, actual_state = _inspect_enabled(module, backend, instance, systemctl, diagnostics)
                expected_enabled = operation == "enable"
                if actual_enabled is not expected_enabled or actual_state != ("enabled" if expected_enabled else "disabled"):
                    raise IndexerError("Indexer enablement did not reach %s for %s (observed %s)" %
                                       (expected_enabled, instance, actual_state))

        final_state = _inspect_runtime(module, binary, backend, instance, systemctl, p["quiet"], diagnostics)
        final_enabled, enablement_state = _inspect_enabled(module, backend, instance, systemctl, diagnostics)
        if desired_state == "started" and final_state != "started":
            raise IndexerError("Indexer postcondition failed: expected started, observed %s" % final_state)
        if desired_state == "stopped" and final_state != "stopped":
            raise IndexerError("Indexer postcondition failed: expected stopped, observed %s" % final_state)
        if desired_state == "restarted" and final_state != "started":
            raise IndexerError("koha-indexer --restart did not leave the service started (observed %s)" % final_state)
        if desired_enabled is not None and final_enabled is not desired_enabled:
            raise IndexerError("Indexer enablement postcondition failed: expected %s, observed %s" %
                               (desired_enabled, enablement_state))
        module.exit_json(changed=changed_any, instance=instance, backend=backend, state=final_state,
                         previous_state=previous_state, enabled=final_enabled, previous_enabled=previous_enabled,
                         enablement_state=enablement_state, search_engine=search_engine, zebra_running=zebra_running,
                         actions=actions, planned_actions=[], diagnostics=diagnostics,
                         msg="Indexer operations completed" if changed_any else "Indexer already matches requested state")
    except IndexerError as exc:
        module.fail_json(msg=str(exc), changed=changed_any, instance=instance, backend=backend,
                         state=final_state or previous_state, previous_state=previous_state,
                         enabled=final_enabled if final_enabled is not None else previous_enabled,
                         previous_enabled=previous_enabled, enablement_state=enablement_state,
                         search_engine=search_engine, zebra_running=zebra_running,
                         actions=actions, planned_actions=[], actions_status="attempted" if actions else "none",
                         diagnostics=diagnostics)


if __name__ == "__main__":
    main()
