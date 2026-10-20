# SPDX-License-Identifier: MIT-0
#!/usr/bin/python
"""Run a one-shot Zebra index update for a Koha instance."""

DOCUMENTATION = r'''
---
module: zebra_rebuild
short_description: Run a one-shot Zebra index update for a Koha instance
description:
  - Invokes the packaged C(koha-rebuild-zebra) interface for exactly one Koha instance.
  - Supports incremental and explicitly requested full rebuilds of bibliographic indexes, authority indexes, or both.
  - This is an imperative operation and does not manage Zebra or indexer services.
  - A completed command does not prove index integrity or report a record count.
version_added: "1.3.0"
author: Jonas MZ
requirements:
  - Debian or Ubuntu Koha package providing C(koha-rebuild-zebra), C(koha-list), C(koha-shell), C(koha-zebra), and Koha service helpers
  - Root privileges (use C(become: true))
options:
  instance:
    description: One existing Koha instance name. Loop over instances for multiple operations.
    type: str
    required: true
  mode:
    description: C(incremental) processes pending updates; C(full) explicitly requests rebuilding the selected collections.
    type: str
    choices: [incremental, full]
    default: incremental
  target:
    description: Which Zebra index collections to process.
    type: str
    choices: [all, biblios, authorities]
    default: all
  force:
    description: Pass C(--force) for incremental work when C(USE_INDEXER_DAEMON) is enabled. Does not bypass other checks.
    type: bool
    default: false
  verbose:
    description: Number of C(--verbose) flags to pass (0 to 3). Use 0 with C(quiet: true).
    type: int
    choices: [0, 1, 2, 3]
    default: 1
  quiet:
    description: Pass C(--quiet). Cannot be combined with a nonzero C(verbose) value.
    type: bool
    default: false
  verify_search_engine:
    description: Read Koha's C(SearchEngine) preference and require C(Zebra). Failure to read it is an error.
    type: bool
    default: true
  require_zebra_running:
    description: Require the instance's Zebra service to be running. The service is never started by this module.
    type: bool
    default: false
  command_path:
    description: Absolute path to the C(koha-rebuild-zebra) executable.
    type: path
    default: /usr/sbin/koha-rebuild-zebra
notes:
  - Full rebuilds can consume substantial CPU, memory, disk space, and I/O and may reduce search availability while indexes are regenerated.
  - The command's upstream output and exit status do not prove functional index integrity. Known warnings and lock failures are classified, but unrecognized output is reported as C(unknown).
  - The installed command's C(--help) is checked for each requested option. Koha package behavior varies by release; this module has not been validated against every Koha release.
  - Incremental work is skipped by Koha when C(USE_INDEXER_DAEMON) is not exactly C(no), unless C(force: true) is used. The module reads only a simple static setting from C(/etc/default/koha-common); dynamic or unreadable settings fail closed.
  - Koha's own rebuild lock is respected. The module does not remove lock files, wait indefinitely, stop services, or retry failed work.
  - C(async) and C(poll) are Ansible task controls and can be used for long-running full rebuilds.
  - This operation is imperative: successful execution reports C(changed: true), including an incremental pass that finds no records to change.
  - In check mode, read-only validations run and the intended command is returned without invoking it.
'''

EXAMPLES = r'''
- name: Initial full Zebra rebuild after starting Zebra
  jmz.koha.zebra_rebuild:
    instance: biblioteca
    mode: full
    target: all
    require_zebra_running: true
  become: true

- name: Incrementally update only bibliographic indexes
  jmz.koha.zebra_rebuild:
    instance: biblioteca
    target: biblios
  become: true

- name: Force incremental authority indexing when the daemon is enabled
  jmz.koha.zebra_rebuild:
    instance: biblioteca
    target: authorities
    force: true
  become: true

- name: Rebuild several instances independently
  jmz.koha.zebra_rebuild:
    instance: "{{ item }}"
    mode: full
  loop: [biblioteca, archivo]
  become: true

- name: Run a long full rebuild under Ansible async supervision
  jmz.koha.zebra_rebuild:
    instance: biblioteca
    mode: full
  async: 7200
  poll: 30
  become: true

- name: Preview the operation and all read-only preflight checks
  jmz.koha.zebra_rebuild:
    instance: biblioteca
    mode: incremental
  check_mode: true
  become: true
'''

RETURN = r'''
instance:
  description: Koha instance selected.
  returned: always
  type: str
mode:
  description: Requested operation mode.
  returned: always
  type: str
target:
  description: Requested index target.
  returned: always
  type: str
status:
  description: Normalized result, C(completed), C(skipped), C(blocked), C(failed), or C(unknown).
  returned: always
  type: str
executed:
  description: Whether the rebuild utility was invoked.
  returned: always
  type: bool
skipped:
  description: Whether Koha or preflight rules skipped the requested work.
  returned: always
  type: bool
skip_reason:
  description: Explanation when work was skipped.
  returned: always
  type: str
command:
  description: Safe argv representation of the planned or executed command(s).
  returned: always
  type: list
  elements: list
rc:
  description: Return code for one target, or null when there are multiple targets or execution did not occur.
  returned: always
  type: int
duration:
  description: Total rebuild invocation time in seconds, or null when not executed.
  returned: always
  type: float
search_engine:
  description: Verified SearchEngine preference, or null when verification was disabled.
  returned: always
  type: str
zebra_running:
  description: Zebra runtime observation when required, otherwise null.
  returned: always
  type: bool
target_results:
  description: Per-target results. Record counts are null because command output is not a stable count interface.
  returned: always
  type: dict
stdout:
  description: Combined bounded stdout from rebuild invocations.
  returned: always
  type: str
stderr:
  description: Combined bounded stderr from rebuild invocations.
  returned: always
  type: str
msg:
  description: Human-readable summary.
  returned: always
  type: str
'''

import grp
import os
import pwd
import re
import shlex
import time

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import choice_normalizer


INSTANCE_RE = re.compile(r"^[a-z][a-z0-9-]{0,10}$")
OUTPUT_LIMIT = 12000
TARGET_FLAGS = {"biblios": "--biblios", "authorities": "--authorities"}
WARNING_PATTERNS = (
    (re.compile(r"something went wrong rebuilding biblio indexes", re.I), "biblios", "failed"),
    (re.compile(r"something went wrong rebuilding authority indexes", re.I), "authorities", "failed"),
    (re.compile(r"unknown instance", re.I), None, "failed"),
    (re.compile(r"(?:unable|failed|could not|cannot|can't).{0,80}(?:obtain|acquire|create|get).{0,40}lock|lock.{0,50}(?:busy|unavailable|failed|already exists)", re.I), None, "blocked"),
    (re.compile(r"(?:continuing|proceeding|running).{0,50}without.{0,30}lock|without.{0,30}(?:a )?lock.{0,30}(?:continue|proceed|run)", re.I), None, "blocked"),
    (re.compile(r"(?:skipped|skipping).{0,80}(?:rebuild|index(?:ing)?|bibliographic|authority)", re.I), None, "skipped"),
    (re.compile(r"\b(?:fatal|error|failed|failure)\b", re.I), None, "failed"),
    (re.compile(r"\bwarning\b", re.I), None, "unknown"),
)


class RebuildError(Exception):
    """Unsafe or unverified rebuild request."""


def _bounded(value):
    return (value or "")[:OUTPUT_LIMIT]


def _run(module, argv, diagnostics, operation):
    try:
        rc, stdout, stderr = module.run_command(argv)
    except OSError as exc:
        diagnostics.append(dict(operation=operation, command=argv, rc=None, stdout="", stderr=_bounded(str(exc))))
        raise RebuildError("Unable to execute %s: %s" % (argv[0], exc))
    stdout, stderr = stdout or "", stderr or ""
    diagnostics.append(dict(operation=operation, command=argv, rc=rc,
                            stdout=_bounded(stdout), stderr=_bounded(stderr)))
    return rc, stdout, stderr


def validate_arguments(p):
    if not INSTANCE_RE.fullmatch(p["instance"] or ""):
        raise RebuildError("instance must be 1-11 lowercase letters, digits, or hyphens, starting with a letter")
    if p["mode"] == "full" and p["force"]:
        raise RebuildError("force is only valid with mode=incremental; mode=full already bypasses USE_INDEXER_DAEMON")
    if p["quiet"] and p["verbose"] > 0:
        raise RebuildError("quiet=true conflicts with verbose greater than 0; set verbose=0")
    if not os.path.isabs(p["command_path"]):
        raise RebuildError("command_path must be absolute")


def validate_instance(module, instance, diagnostics):
    config = "/etc/koha/sites/%s/koha-conf.xml" % instance
    site = "/etc/koha/sites/%s" % instance
    if not os.path.isdir(site) or not os.path.isfile(config):
        raise RebuildError("Koha instance %s does not exist or its koha-conf.xml is missing" % instance)
    binary = module.get_bin_path("koha-list", required=False)
    if not binary:
        raise RebuildError("koha-list was not found; cannot independently verify instance %s" % instance)
    rc, stdout, stderr = _run(module, [binary], diagnostics, "verify_instance")
    if rc != 0 or instance not in stdout.splitlines():
        raise RebuildError("koha-list did not confirm instance %s (rc=%s): %s" %
                           (instance, rc, _bounded(stderr or stdout).strip()))
    try:
        pwd.getpwnam(instance + "-koha")
        grp.getgrnam(instance + "-koha")
    except KeyError:
        raise RebuildError("system user or group %s-koha does not exist" % instance)
    if os.geteuid() != 0:
        raise RebuildError("root privileges are required to invoke koha-rebuild-zebra safely; run this task with become: true")


def resolve_command(module, path):
    resolved = path
    if path == "/usr/sbin/koha-rebuild-zebra":
        resolved = module.get_bin_path("koha-rebuild-zebra", required=False)
        if not resolved:
            raise RebuildError("koha-rebuild-zebra was not found on the managed host")
    if not os.path.isabs(resolved) or not os.path.isfile(resolved) or not os.access(resolved, os.X_OK):
        raise RebuildError("koha-rebuild-zebra is missing or not executable: %s" % resolved)
    return resolved


def detect_search_engine(module, instance, diagnostics):
    shell = module.get_bin_path("koha-shell", required=False)
    pref = "/usr/share/koha/bin/admin/koha-preferences"
    if not shell or not os.path.isfile(pref) or not os.access(pref, os.X_OK):
        raise RebuildError("Cannot verify SearchEngine: koha-shell or executable koha-preferences is unavailable")
    # instance is restricted to safe Koha instance characters; the payload is one argv item.
    rc, stdout, stderr = _run(module, [shell, instance, "-c", "%s get SearchEngine 2>/dev/null" % pref],
                              diagnostics, "inspect_search_engine")
    value = stdout.strip()
    if rc != 0 or value not in ("Zebra", "Elasticsearch"):
        raise RebuildError("Unable to reliably read SearchEngine for %s (rc=%s): %s" %
                           (instance, rc, _bounded(stderr or stdout).strip() or "unrecognized value"))
    if value != "Zebra":
        raise RebuildError("Refusing Zebra rebuild for %s: SearchEngine is %s" % (instance, value))
    return value


def check_zebra_service(module, instance, diagnostics):
    binary = module.get_bin_path("koha-zebra", required=False)
    if not binary:
        raise RebuildError("Cannot verify Zebra runtime: koha-zebra was not found")
    rc, stdout, stderr = _run(module, [binary, "--status", instance], diagnostics, "inspect_zebra")
    text = (stdout + "\n" + stderr).lower()
    escaped = re.escape(instance.lower())
    if re.search(r"zebra[^\n]*(?:not running|stopped)[^\n]*\b%s\b|not running for instance\s+%s\b" %
                 (escaped, escaped), text):
        return False
    if re.search(r"zebra[^\n]*running[^\n]*\b%s\b|running for instance\s+%s\b" % (escaped, escaped), text):
        return True
    raise RebuildError("Unable to determine Zebra runtime for %s (rc=%s): %s" %
                       (instance, rc, _bounded(stderr or stdout).strip() or "unrecognized status"))


def inspect_indexer_configuration():
    """Read only a static USE_INDEXER_DAEMON assignment, never source root shell code."""
    path = "/etc/default/koha-common"
    if not os.path.isfile(path):
        # The wrapper sources this file optionally; an unset variable does not equal 'no'.
        return "enabled_or_unset"
    try:
        with open(path, "r", encoding="utf-8") as stream:
            lines = stream.readlines()
    except OSError as exc:
        raise RebuildError("Unable to inspect %s safely: %s" % (path, exc))
    setting = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "USE_INDEXER_DAEMON" not in stripped:
            continue
        match = re.fullmatch(r"(?:export\s+)?USE_INDEXER_DAEMON\s*=\s*(.*?)\s*(?:#.*)?", stripped)
        if not match:
            raise RebuildError("USE_INDEXER_DAEMON is configured dynamically; refusing to guess whether incremental work will run")
        raw = match.group(1)
        try:
            words = shlex.split(raw, comments=False, posix=True)
        except ValueError:
            raise RebuildError("USE_INDEXER_DAEMON cannot be parsed safely")
        if len(words) > 1 or (words and not re.fullmatch(r"[A-Za-z0-9_-]+", words[0])):
            raise RebuildError("USE_INDEXER_DAEMON is not a simple static value; refusing to guess")
        setting = words[0] if words else ""
    # koha-rebuild-zebra proceeds incrementally only when the value is exactly 'no'.
    return "disabled" if setting == "no" else "enabled_or_unset"


def validate_rebuild_request(module, p, diagnostics):
    validate_arguments(p)
    validate_instance(module, p["instance"], diagnostics)
    binary = resolve_command(module, p["command_path"])
    help_rc, help_out, help_err = _run(module, [binary, "--help"], diagnostics, "inspect_cli_options")
    help_text = help_out + "\n" + help_err
    expected = ["--full"] if p["mode"] == "full" else []
    expected += [TARGET_FLAGS[key] for key in ("biblios", "authorities") if p["target"] in ("all", key)]
    if p["force"]:
        expected.append("--force")
    if p["quiet"]:
        expected.append("--quiet")
    if p["verbose"]:
        expected.append("--verbose")
    if help_rc != 0:
        raise RebuildError("Unable to inspect koha-rebuild-zebra --help (rc=%s): %s" %
                           (help_rc, _bounded(help_err or help_out).strip()))
    for option in expected:
        if not re.search(r"(?m)(?:^|\s)%s(?:\s|$|\|)" % re.escape(option), help_text):
            raise RebuildError("Installed koha-rebuild-zebra does not advertise required option %s" % option)
    engine = detect_search_engine(module, p["instance"], diagnostics) if p["verify_search_engine"] else None
    zebra = check_zebra_service(module, p["instance"], diagnostics) if p["require_zebra_running"] else None
    if p["require_zebra_running"] and not zebra:
        raise RebuildError("Zebra is not running for %s; start it with jmz.koha.zebra before rebuilding" % p["instance"])
    indexer = inspect_indexer_configuration() if p["mode"] == "incremental" else None
    return binary, engine, zebra, indexer


def build_rebuild_command(binary, p, target):
    argv = [binary]
    if p["mode"] == "full":
        argv.append("--full")
    if target in TARGET_FLAGS:
        argv.append(TARGET_FLAGS[target])
    if p["force"]:
        argv.append("--force")
    if p["quiet"]:
        argv.append("--quiet")
    argv.extend(["--verbose"] * p["verbose"])
    argv.append(p["instance"])
    return argv


def parse_target_results(targets, outputs):
    results = {key: dict(status="unknown", executed=False, rc=None, records_processed=None, msg="Not processed")
               for key in ("biblios", "authorities")}
    for target in targets:
        rc, stdout, stderr = outputs[target]
        text = stdout + "\n" + stderr
        result = dict(status="unknown", executed=True, rc=rc, records_processed=None,
                      msg="Command completed but the index outcome could not be verified")
        for pattern, affected, status in WARNING_PATTERNS:
            if pattern.search(text) and (affected is None or affected == target):
                result.update(status=status, msg="Recognized Koha diagnostic: %s" % pattern.pattern)
                break
        else:
            if rc != 0:
                result.update(status="failed", msg="koha-rebuild-zebra returned a nonzero status")
            elif text.strip():
                # Zero exit status alone is not treated as proof; require no known error and output from the selected pass.
                result.update(status="completed", msg="The selected Koha pass returned successfully without recognized failure or skip diagnostics; index integrity was not checked")
            else:
                result.update(status="unknown", msg="No output or independent completion evidence was available")
        results[target] = result
    return results


def classify_execution_result(target_results):
    statuses = [v["status"] for v in target_results.values() if v["executed"]]
    if not statuses:
        return "unknown"
    if "blocked" in statuses:
        return "blocked"
    if "failed" in statuses:
        return "failed"
    if "unknown" in statuses:
        return "unknown"
    if all(status == "skipped" for status in statuses):
        return "skipped"
    return "completed"


def build_module_result(p, targets, commands, status, executed, skipped, skip_reason, engine,
                        zebra, target_results, stdout, stderr, duration, rc=None):
    return dict(instance=p["instance"], mode=p["mode"], target=p["target"], status=status,
                executed=executed, skipped=skipped, skip_reason=skip_reason,
                command=commands, rc=rc, duration=duration, search_engine=engine,
                zebra_running=zebra, target_results=target_results,
                stdout=_bounded(stdout), stderr=_bounded(stderr))


def main():
    module = AnsibleModule(
        argument_spec=dict(
            instance=dict(type="str", required=True),
            mode=dict(type=choice_normalizer(["incremental", "full"]), choices=["incremental", "full"], default="incremental"),
            target=dict(type=choice_normalizer(["all", "biblios", "authorities"]), choices=["all", "biblios", "authorities"], default="all"),
            force=dict(type="bool", default=False),
            verbose=dict(type="int", choices=[0, 1, 2, 3], default=1),
            quiet=dict(type="bool", default=False),
            verify_search_engine=dict(type="bool", default=True),
            require_zebra_running=dict(type="bool", default=False),
            command_path=dict(type="path", default="/usr/sbin/koha-rebuild-zebra"),
        ), supports_check_mode=True,
    )
    p = module.params
    diagnostics = []
    targets = ["biblios", "authorities"] if p["target"] == "all" else [p["target"]]
    empty_results = {key: dict(status="unknown", executed=False, rc=None, records_processed=None, msg="Not processed")
                     for key in ("biblios", "authorities")}
    commands = []
    try:
        binary, engine, zebra, indexer = validate_rebuild_request(module, p, diagnostics)
        commands = [build_rebuild_command(binary, p, target) for target in targets]
        if p["mode"] == "incremental" and indexer == "enabled_or_unset" and not p["force"]:
            reason = "USE_INDEXER_DAEMON is not confirmed as 'no'; koha-rebuild-zebra would omit incremental work. Set force=true only after coordinating the indexer."
            result = build_module_result(p, targets, commands, "skipped", False, True, reason, engine, zebra,
                                         empty_results, "", "", None)
            result["changed"] = False
            result["msg"] = reason
            module.exit_json(**result)
        if module.check_mode:
            for target in targets:
                empty_results[target].update(status="unknown", msg="Would be attempted; check mode does not inspect pending records")
            result = build_module_result(p, targets, commands, "unknown", False, False, None, engine, zebra,
                                         empty_results, "", "", None)
            result["changed"] = True
            result["msg"] = "Check mode: validated and planned the %s %s operation; index changes are not guaranteed" % (p["mode"], p["target"])
            module.exit_json(**result)
        outputs = {}
        all_stdout, all_stderr, codes = [], [], []
        start = time.monotonic()
        for target, argv in zip(targets, commands):
            try:
                rc, stdout, stderr = _run(module, argv, diagnostics, "rebuild_%s" % target)
            except RebuildError as exc:
                outputs[target] = (None, "", str(exc))
                codes.append(None)
                all_stderr.append(str(exc))
                # A previous target may already have modified indexes.
                target_results = parse_target_results(list(outputs), outputs)
                target_results[target].update(executed=False, rc=None, status="failed", msg=str(exc))
                status = classify_execution_result(target_results)
                duration = max(0.0, time.monotonic() - start)
                result = build_module_result(p, targets, commands, status, bool(len(outputs) > 1), False, None,
                                             engine, zebra, target_results, "\n".join(all_stdout),
                                             "\n".join(all_stderr), duration,
                                             codes[0] if len(codes) == 1 else None)
                result.update(changed=len(outputs) > 1, msg="Unable to execute target %s after %s target(s): %s" %
                              (target, len(outputs) - 1, exc), diagnostics=diagnostics)
                module.fail_json(**result)
            outputs[target] = (rc, stdout, stderr)
            all_stdout.append(stdout)
            all_stderr.append(stderr)
            codes.append(rc)
        duration = max(0.0, time.monotonic() - start)
        target_results = parse_target_results(targets, outputs)
        status = classify_execution_result(target_results)
        result = build_module_result(p, targets, commands, status, True, False, None, engine, zebra,
                                     target_results, "\n".join(all_stdout), "\n".join(all_stderr), duration,
                                     codes[0] if len(codes) == 1 else None)
        skipped_targets = [target for target in targets if target_results[target]["status"] == "skipped"]
        all_skipped = status == "skipped"
        result["changed"] = not all_skipped
        if skipped_targets:
            result.update(skipped=True, skip_reason="Koha reported skipped index work for: %s" % ", ".join(skipped_targets))
        if status in ("failed", "blocked", "unknown"):
            result["msg"] = "Zebra operation %s for %s: %s" % (status, p["instance"], ", ".join(
                "%s=%s" % (t, target_results[t]["status"]) for t in targets))
            result["diagnostics"] = diagnostics
            module.fail_json(**result)
        result["msg"] = ("Koha reported the selected index pass was skipped for %s" % p["instance"] if all_skipped else
                          "Koha rebuild command completed for %s (%s); index integrity was not checked" % (p["instance"], p["target"]))
        result["diagnostics"] = diagnostics
        module.exit_json(**result)
    except RebuildError as exc:
        result = build_module_result(p, targets, commands, "failed", False, False, None, None, None,
                                     empty_results, "", "", None)
        result.update(changed=False, msg=str(exc), diagnostics=diagnostics)
        module.fail_json(**result)


if __name__ == "__main__":
    main()
