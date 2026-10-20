# SPDX-License-Identifier: MIT-0
#!/usr/bin/python
"""Manage Koha translations through koha-translate."""

DOCUMENTATION = r'''
---
module: translate
short_description: Manage Koha translations declaratively
description:
  - Ensures a translation is installed or absent using the official koha-translate command.
  - The default Debian scope is the shared Koha installation, not an individual library instance.
version_added: "1.4.0"
author: Jonas MZ
requirements:
  - Debian or Ubuntu Koha package providing koha-translate, Koha helper files, and translation resources (normally koha-l10n).
  - Root privileges; use become: true.
options:
  name:
    description: Exact Koha language code, for example es-ES or fr-CA.
    type: str
    required: true
    aliases: [language, lang_code]
  state:
    description: Whether the translation should be installed or absent.
    type: str
    choices: [present, absent]
    default: present
  update:
    description: Explicitly regenerate an installed translation. Koha removes it before reinstalling it, so a failure can leave it absent.
    type: bool
    default: false
  dev_instance:
    description: Existing Koha instance configured with git_install or legacy dev_install. Selects that development checkout only; production instances are rejected.
    type: str
  verbose:
    description: Ask koha-translate for detailed output. Its four-argument limit prevents combining this with dev_instance.
    type: bool
    default: false
notes:
  - Without dev_instance, translations are generated in the shared Debian Koha tree, not privately for one production instance. Install and remove clear caches for enabled instances globally.
  - dev_instance requires an existing Koha config marked as a Git/development install. The module never falls back to global scope.
  - available checks only for an OPAC PO file. Before install/update, the module also runs --check for required MARC21, UNIMARC, OPAC, preference, and staff PO files; neither check proves runtime functionality.
  - Koha update removes then reinstalls and is not atomic. Required PO files are checked first and the resulting installed list is verified; rollback is not promised.
  - Koha 26.05.x install and remove clear cache; update does not call the cache helper. This module adds no extra cache operation.
  - Installing templates does not enable OPACLanguages or StaffInterfaceLanguages, configure user languages, or change the database.
  - Modifications are coordinated with a local flock under /run/lock. External koha-translate invocations do not use this lock.
  - update=true can report changed on every run; Koha exposes no reliable translation-source version check.
  - English en is built in and cannot be installed, updated, or removed.
  - Designed against Koha 26.05.x and the matching current upstream interface. Validate the installed package before relying on another branch.
  - Check mode performs read-only queries and reports the planned action. Diff mode reports semantic installed state, not generated PO/template file contents.
'''

EXAMPLES = r'''
- name: Install Spanish translation in the shared Koha tree
  jmz.koha.translate:
    name: es-ES
    state: present
  become: true

- name: Ensure French translation is absent
  jmz.koha.translate:
    name: fr-FR
    state: absent
  become: true

- name: Explicitly regenerate Spanish translation templates
  jmz.koha.translate:
    name: es-ES
    state: present
    update: true
  become: true

- name: Install Spanish templates in a development checkout
  jmz.koha.translate:
    name: es-ES
    state: present
    dev_instance: koha-dev
  become: true

- name: Preview an installation
  jmz.koha.translate:
    name: es-ES
    state: present
  check_mode: true
  diff: true
  become: true
'''

RETURN = r'''
name:
  description: Exact language code requested.
  returned: always
  type: str
state:
  description: Requested declarative state.
  returned: always
  type: str
installed:
  description: Whether the exact code is installed at the end; en is treated as built in.
  returned: always
  type: bool
available:
  description: Whether Koha listed the exact code as available, or null when it was not queried.
  returned: always
  type: bool
action_executed:
  description: Mutation actually executed, or null when none occurred.
  returned: always
  type: str
planned_action:
  description: Mutation predicted in check mode, or null when no change is needed.
  returned: when check mode
  type: str
scope:
  description: global or development.
  returned: always
  type: str
dev_instance:
  description: Selected development instance, or null for global scope.
  returned: always
  type: str
cmd:
  description: Safe argv list for the last command or planned mutation.
  returned: always
  type: list
  elements: str
rc:
  description: Return code of the last command, or null when none ran.
  returned: always
  type: int
stdout:
  description: Bounded stdout from the last command.
  returned: always
  type: str
stderr:
  description: Bounded stderr from the last command.
  returned: always
  type: str
msg:
  description: Human-readable outcome or planned operation.
  returned: always
  type: str
'''

import contextlib
import fcntl
import hashlib
import os
import re
import time
import xml.etree.ElementTree as ET

from ansible.module_utils.basic import AnsibleModule


LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
INSTANCE_RE = re.compile(r"^[a-z][a-z0-9-]{0,10}$")
OUTPUT_LIMIT = 6000
LOCK_TIMEOUT = 30
REQUIRED_HELP_OPTIONS = ("--list", "--available", "--check", "--install", "--update", "--remove", "--dev")


class TranslateError(Exception):
    """A safe validation, command, or verification error."""

    def __init__(self, message, result=None):
        super().__init__(message)
        self.result = result


def _bounded(value):
    """Limit command output included in a module result."""
    return (value or "")[:OUTPUT_LIMIT]


def validate_language(value):
    """Accept common Koha language identifiers and reject paths/options."""
    if not isinstance(value, str) or not LANGUAGE_RE.fullmatch(value):
        raise TranslateError("name must be a language code such as es-ES (letters and digits separated by hyphens)")
    return value


def validate_instance(value):
    """Validate the instance syntax accepted by Koha Debian helpers."""
    if not isinstance(value, str) or not INSTANCE_RE.fullmatch(value):
        raise TranslateError("dev_instance must be a valid Koha instance name (1-11 lowercase letters, digits, or hyphens; starting with a letter)")
    return value


def _development_tree(instance):
    """Return the checkout root for an existing Koha Git/development instance."""
    config = "/etc/koha/sites/%s/koha-conf.xml" % instance
    if not os.path.isfile(config):
        raise TranslateError("development instance %s does not exist: %s was not found" % (instance, config))
    try:
        root = ET.parse(config).getroot()
    except (ET.ParseError, OSError) as exc:
        raise TranslateError("cannot read Koha configuration for development instance %s: %s" % (instance, exc))
    value = root.findtext("git_install")
    if value is None or not value.strip():
        value = root.findtext("dev_install")
    if value is None or not value.strip() or value.strip() == "0":
        raise TranslateError("dev_instance %s is not configured as a development/Git Koha install (git_install/dev_install is not enabled)" % instance)
    intranetdir = root.findtext("intranetdir")
    if not intranetdir or not os.path.isabs(intranetdir.strip()) or not os.path.isdir(intranetdir.strip()):
        raise TranslateError("development instance %s has no valid intranetdir checkout in %s" % (instance, config))
    return os.path.realpath(intranetdir.strip())


def _command(module, argv, operation):
    """Run argv through Ansible and normalize errors and captured output."""
    try:
        rc, stdout, stderr = module.run_command(argv)
    except OSError as exc:
        raise TranslateError("could not run koha-translate for %s: %s" % (operation, exc))
    result = {"cmd": argv, "rc": rc, "stdout": _bounded(stdout), "stderr": _bounded(stderr)}
    if rc != 0:
        detail = (stderr or stdout or "no diagnostic output").strip()
        raise TranslateError("koha-translate %s failed (rc=%s): %s" % (operation, rc, _bounded(detail)), result=result)
    return result


def _scope_args(dev_instance):
    """Return the native CLI suffix for the selected scope."""
    return ["--dev", dev_instance] if dev_instance else []


def _query_languages(module, binary, mode, dev_instance):
    """Query and normalize exact installed or available language identifiers."""
    if mode == "installed":
        argv = [binary, "--list"] + _scope_args(dev_instance)
    elif mode == "available":
        argv = [binary, "--list", "--available"] + _scope_args(dev_instance)
    else:
        raise TranslateError("unsupported language query: %s" % mode)
    try:
        result = _command(module, argv, "language list query")
    except TranslateError as exc:
        # Koha 26.05.x uses `set -e` and ends `--list` with grep -v. When
        # there are no non-English translations installed, grep finds no
        # lines and the script exits 1 without diagnostics. Treat that exact
        # result as an empty installed-language list; other failures remain
        # errors. The available-language query has different semantics.
        result = exc.result
        if not (mode == "installed" and result and result.get("rc") == 1
                and not result.get("stdout") and not result.get("stderr")):
            raise
    languages = []
    seen = set()
    for raw in result["stdout"].splitlines():
        code = raw.strip()
        if not code:
            continue
        if not LANGUAGE_RE.fullmatch(code):
            raise TranslateError("koha-translate returned unexpected %s output: %s" % (mode, _bounded(code)))
        if code not in seen:
            seen.add(code)
            languages.append(code)
    return languages, result


def _check_po_files(module, binary, name, dev_instance):
    """Ask Koha to check the PO files required by its translation script."""
    argv = [binary, "--check", name] + _scope_args(dev_instance)
    try:
        return _command(module, argv, "--check %s" % name)
    except TranslateError as exc:
        message = str(exc)
        if "not found" in message.lower() or "no such file" in message.lower():
            raise TranslateError("required PO files are incomplete for %s; install or repair translation resources (usually koha-l10n): %s" % (name, message))
        raise


def _verify_cli(module, binary, verbose):
    """Require installed help output to advertise the interface used here."""
    result = _command(module, [binary, "--help"], "--help compatibility check")
    help_text = result["stdout"] + "\n" + result["stderr"]
    missing = [option for option in REQUIRED_HELP_OPTIONS if option not in help_text]
    if verbose and "--verbose" not in help_text:
        missing.append("--verbose")
    if missing:
        raise TranslateError("installed koha-translate does not advertise required options: %s" % ", ".join(missing))
    return result


def _planned_argv(binary, action, name, dev_instance, verbose):
    """Build native argv after validating the CLI argument limit."""
    argv = [binary, "--" + action, name]
    if verbose:
        argv.append("--verbose")
    argv.extend(_scope_args(dev_instance))
    if len(argv) - 1 > 4:
        raise TranslateError("this koha-translate version accepts at most four arguments; verbose cannot be combined with dev_instance")
    return argv


def _lock_path(dev_instance, dev_root=None):
    """Return a lock path for the actual shared or development resource."""
    if dev_instance:
        if not dev_root:
            raise TranslateError("development checkout path is required to select its translation lock")
        digest = hashlib.sha256(os.path.realpath(dev_root).encode("utf-8")).hexdigest()[:20]
        return "/run/lock/jmz-koha-translate-dev-%s.lock" % digest
    return "/run/lock/jmz-koha-translate-global.lock"


@contextlib.contextmanager
def _mutation_lock(path, timeout=LOCK_TIMEOUT):
    """Acquire a bounded local flock and release it on every exit path."""
    try:
        handle = open(path, "a", encoding="utf-8")
    except OSError as exc:
        raise TranslateError("cannot open translation lock %s: %s (run with become: true)" % (path, exc))
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TranslateError("timed out waiting for translation lock %s; another module operation may be active" % path)
                time.sleep(0.1)
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _need_action(state, installed, update):
    """Calculate the mutation needed for the requested state."""
    if state == "absent":
        return "remove" if installed else None
    if installed:
        return "update" if update else None
    return "install"


def _payload(name, state, dev_instance, installed, available, last, action=None, planned=None, msg=""):
    """Prepare consistent safe JSON output fields."""
    return {
        "name": name, "state": state, "installed": installed, "available": available,
        "scope": "development" if dev_instance else "global", "dev_instance": dev_instance,
        "action_executed": action, "planned_action": planned,
        "cmd": last.get("cmd", []) if last else [], "rc": last.get("rc") if last else None,
        "stdout": last.get("stdout", "") if last else "", "stderr": last.get("stderr", "") if last else "",
        "msg": msg,
    }


def main():
    """Observe state, plan the minimum operation, and verify any mutation."""
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type="str", required=True, aliases=["language", "lang_code"]),
            state=dict(type="str", choices=["present", "absent"], default="present"),
            update=dict(type="bool", default=False),
            dev_instance=dict(type="str"),
            verbose=dict(type="bool", default=False),
        ), supports_check_mode=True,
    )
    p = module.params
    name, state = p["name"], p["state"]
    update, dev_instance, verbose = p["update"], p["dev_instance"], p["verbose"]
    last = None
    installed = None
    available = None
    dev_root = None

    try:
        validate_language(name)
        if dev_instance is not None:
            validate_instance(dev_instance)
            dev_root = _development_tree(dev_instance)
        if update and state != "present":
            raise TranslateError("update: true is only valid with state: present")
        if verbose and dev_instance:
            raise TranslateError("verbose cannot be combined with dev_instance: koha-translate accepts at most four argv items")
        if name == "en" and state == "absent":
            raise TranslateError("the built-in English language en cannot be removed")
        if name == "en" and update:
            raise TranslateError("the built-in English language en cannot be updated")

        binary = module.get_bin_path("koha-translate", required=False)
        if not binary or not os.path.isfile(binary) or not os.access(binary, os.X_OK):
            raise TranslateError("koha-translate was not found or is not executable; install the Koha package providing it")
        last = _verify_cli(module, binary, verbose)
        if name == "en":
            result = _payload(name, state, dev_instance, True, None, last, msg="English (en) is Koha's built-in base language")
            if module._diff:
                result["diff"] = {"before": {"installed": True}, "after": {"installed": True}}
            module.exit_json(changed=False, **result)

        installed_codes, last = _query_languages(module, binary, "installed", dev_instance)
        installed = name in installed_codes
        action = _need_action(state, installed, update)
        if action in ("install", "update"):
            available_codes, last = _query_languages(module, binary, "available", dev_instance)
            available = name in available_codes
            if not available:
                raise TranslateError("language %s is not available in local translation resources; install or repair koha-l10n or the development PO checkout" % name)
            last = _check_po_files(module, binary, name, dev_instance)

        if not action:
            result = _payload(name, state, dev_instance, installed, available, last,
                              msg="translation %s is already %s" % (name, "installed" if state == "present" else "absent"))
            if module._diff:
                result["diff"] = {"before": {"installed": installed}, "after": {"installed": installed}}
            module.exit_json(changed=False, **result)

        mutation_argv = _planned_argv(binary, action, name, dev_instance, verbose)
        if module.check_mode:
            result = _payload(name, state, dev_instance, installed, available, last,
                              planned=action, msg="would %s translation %s" % (action, name))
            result.update(cmd=mutation_argv, planned=True)
            if module._diff:
                result["diff"] = {"before": {"installed": installed}, "after": {"installed": action != "remove"}}
                if action == "update":
                    result["diff"]["regenerated"] = True
            module.exit_json(changed=True, **result)

        with _mutation_lock(_lock_path(dev_instance, dev_root)):
            # Re-read state under the module-local lock to avoid duplicate module work.
            installed_codes, last = _query_languages(module, binary, "installed", dev_instance)
            installed = name in installed_codes
            action = _need_action(state, installed, update)
            if action in ("install", "update"):
                available_codes, last = _query_languages(module, binary, "available", dev_instance)
                available = name in available_codes
                if not available:
                    raise TranslateError("language %s is no longer available in local translation resources" % name)
                last = _check_po_files(module, binary, name, dev_instance)
            if not action:
                result = _payload(name, state, dev_instance, installed, available, last,
                                  msg="translation %s reached the requested state while waiting for the lock" % name)
                module.exit_json(changed=False, **result)
            mutation_argv = _planned_argv(binary, action, name, dev_instance, verbose)
            try:
                last = _command(module, mutation_argv, "--%s %s" % (action, name))
            except TranslateError as exc:
                last = exc.result or last
                result = _payload(name, state, dev_instance, installed, available, last, action=action, msg=str(exc))
                result["partial"] = action in ("update", "remove")
                module.fail_json(changed=True, **result)
            action_result = last
            try:
                installed_codes, last = _query_languages(module, binary, "installed", dev_instance)
            except TranslateError as exc:
                last = exc.result or last
                result = _payload(name, state, dev_instance, None, available, last, action=action,
                                  msg="%s; post-operation state could not be verified and may be partially modified" % exc)
                result["partial"] = True
                module.fail_json(changed=True, **result)
            final_installed = name in installed_codes
            if final_installed != (action != "remove"):
                result = _payload(name, state, dev_instance, final_installed, available, last, action=action,
                                  msg="koha-translate returned success but the requested installed state was not verified")
                result["partial"] = True
                module.fail_json(changed=True, **result)

        result = _payload(name, state, dev_instance, final_installed, available, action_result, action=action,
                          msg="translation %s %s and verified" % (name, {"install": "installed", "update": "updated", "remove": "removed"}[action]))
        if module._diff:
            result["diff"] = {"before": {"installed": installed}, "after": {"installed": final_installed}}
            if action == "update":
                result["diff"]["regenerated"] = True
        module.exit_json(changed=True, **result)

    except TranslateError as exc:
        last = exc.result or last
        module.fail_json(changed=False, name=name, state=state,
                         scope="development" if dev_instance else "global", dev_instance=dev_instance,
                         action_executed=None, planned_action=None,
                         cmd=last.get("cmd", []) if last else [], rc=last.get("rc") if last else None,
                         stdout=last.get("stdout", "") if last else "", stderr=last.get("stderr", "") if last else "",
                         installed=installed, available=available, msg=str(exc))


if __name__ == "__main__":
    main()

