# SPDX-License-Identifier: MIT-0
"""Shared helpers for the modules that manage Koha's per-instance daemons (zebra, indexer, workers)."""

import contextlib
import os
import re
import shlex
import time

from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import NAME_RE, ModuleInputError
from ansible_collections.jmz.koha.plugins.module_utils.koha_lock import exclusive_lock


OUTPUT_LIMIT = 2000
STATES = ["started", "stopped", "restarted", "status"]
DEFAULTS_FILE = "/etc/default/koha-common"
SETTLE_SECONDS = 10


class ServiceError(Exception):
    """A validation or operation error of a Koha daemon."""


def bounded(value):
    return (value or "")[:OUTPUT_LIMIT]


@contextlib.contextmanager
def service_lock(instance):
    """Serialize daemon operations of one instance; waits briefly for a concurrent run."""
    try:
        with exclusive_lock("service", instance,
                            "otra ejecución está modificando los servicios de %s; reintente cuando termine" % instance,
                            wait=30):
            yield
    except ModuleInputError as exc:
        raise ServiceError(str(exc))


def run(module, argv, diagnostics, operation, timeout):
    """Run a command bounded by ``timeout`` seconds and keep a short diagnostic record."""
    wrapper = module.get_bin_path("timeout", required=False)
    command = [wrapper, "-k", "5", str(timeout)] + list(argv) if wrapper else list(argv)
    rc, stdout, stderr = module.run_command(command)
    diagnostics.append(dict(operation=operation, command=list(argv), rc=rc,
                            stdout=bounded(stdout), stderr=bounded(stderr)))
    if wrapper and rc in (124, 137):
        raise ServiceError("%s excedió el límite de %s segundos" % (os.path.basename(argv[0]), timeout))
    return rc, stdout or "", stderr or ""


def find_command(module, name):
    path = module.get_bin_path(name, required=False, opt_dirs=["/usr/sbin", "/usr/bin"])
    if not path:
        raise ServiceError("no se encontró %s en el host administrado; instale los paquetes Koha" % name)
    return path


def check_instance(module, instance, diagnostics, timeout):
    """Require a valid name, a readable configuration and an instance listed by koha-list."""
    if not isinstance(instance, str) or not NAME_RE.fullmatch(instance):
        raise ServiceError("instance debe tener 1-11 caracteres: minúsculas, números o guiones; debe comenzar por letra")
    if not os.path.isfile("/etc/koha/sites/%s/koha-conf.xml" % instance):
        raise ServiceError("La instancia Koha %s no existe (falta su koha-conf.xml)" % instance)
    rc, stdout, stderr = run(module, [find_command(module, "koha-list")], diagnostics, "verify_instance", timeout)
    if rc != 0:
        raise ServiceError("koha-list falló al verificar la instancia %s (rc=%s): %s"
                           % (instance, rc, bounded(stderr or stdout).strip()))
    if instance not in stdout.splitlines():
        raise ServiceError("koha-list no incluye la instancia %s" % instance)


def require_root(module):
    if os.geteuid() != 0:
        raise ServiceError("se requieren privilegios de root para modificar los servicios; use become: true")


def parse_status(label, instance, rc, stdout, stderr):
    """Read a SysV ``koha-* --status`` result; "not running" also contains "running", so it goes first."""
    text = ("%s\n%s" % (stdout, stderr)).lower()
    if "not running" in text:
        return "stopped"
    if "running" in text:
        return "started"
    if rc == 3:
        return "stopped"
    raise ServiceError("no se pudo determinar el estado de %s para %s (rc=%s): %s"
                       % (label, instance, rc, bounded(text).strip() or "sin salida"))


class Daemon(object):
    """One Koha daemon controlled by a ``koha-<name> --start|--stop|--restart|--status`` command."""

    def __init__(self, module, label, command, instance, diagnostics, timeout, flags=(), operation_flags=()):
        self.module, self.label, self.command, self.instance = module, label, command, instance
        self.diagnostics, self.timeout = diagnostics, timeout
        self.flags, self.operation_flags = list(flags), list(operation_flags)

    def status(self):
        argv = [self.command, "--status"] + self.flags + [self.instance]
        rc, stdout, stderr = run(self.module, argv, self.diagnostics, "status_" + self.label, self.timeout)
        return parse_status(self.label, self.instance, rc, stdout, stderr)

    def operate(self, operation):
        argv = [self.command, "--" + operation] + self.flags + self.operation_flags + [self.instance]
        rc, stdout, stderr = run(self.module, argv, self.diagnostics, operation + "_" + self.label, self.timeout)
        if rc != 0:
            message = "%s --%s falló para %s (rc=%s): %s" % (os.path.basename(self.command), operation,
                                                              self.instance, rc, bounded(stderr or stdout).strip())
            if "permission denied" in message.lower() or "must be root" in message.lower():
                message += " (puede requerir privilegios de root; use become: true)"
            raise ServiceError(message)

    def settle(self, expected):
        """Poll until the daemon reports ``expected``; return the last observed state."""
        deadline = time.monotonic() + SETTLE_SECONDS
        while True:
            observed = self.status()
            if observed == expected or time.monotonic() >= deadline:
                return observed
            time.sleep(0.25)


def plan(desired, current):
    if desired == "restarted":
        return ["restart"]
    if desired == "started" and current == "stopped":
        return ["start"]
    if desired == "stopped" and current == "started":
        return ["stop"]
    return []


def reconcile(daemon, desired, check_mode, progress):
    """Bring one daemon to ``desired``; ``progress`` collects executed actions and whether anything changed.

    Returns (previous_state, final_state). In check mode final_state is the projected state.
    """
    previous = daemon.status()
    actions = plan(desired, previous)
    final = previous
    for operation in actions:
        expected = "stopped" if operation == "stop" else "started"
        if check_mode:
            progress["actions"].append(operation)
            progress["changed"] = True
            final = expected
            continue
        progress["actions"].append(operation)
        try:
            daemon.operate(operation)
        except ServiceError:
            # A failed restart may still have restarted the process; a failed start/stop may have taken effect.
            progress["changed"] = progress["changed"] or operation == "restart" or _differs(daemon, previous)
            raise
        progress["changed"] = True
        final = daemon.settle(expected)
        if final != expected:
            raise ServiceError("%s no llegó al estado %s tras --%s para %s (estado observado: %s)"
                               % (daemon.label, expected, operation, daemon.instance, final))
    return previous, final


def _differs(daemon, previous):
    try:
        return daemon.status() != previous
    except ServiceError:
        return False


def search_engine(module, instance, diagnostics, timeout):
    """Read the SearchEngine preference through koha-shell."""
    koha_shell = find_command(module, "koha-shell")
    preferences = "/usr/share/koha/bin/admin/koha-preferences"
    if not os.path.isfile(preferences) or not os.access(preferences, os.X_OK):
        raise ServiceError("no se puede verificar SearchEngine: falta la utilidad koha-preferences")
    rc, stdout, stderr = run(module, [koha_shell, instance, "-c", "%s get SearchEngine 2>/dev/null" % preferences],
                             diagnostics, "inspect_search_engine", timeout)
    value = stdout.strip()
    if rc != 0 or value not in ("Zebra", "Elasticsearch"):
        raise ServiceError("no se pudo leer SearchEngine de %s (rc=%s): %s"
                           % (instance, rc, bounded(stderr or stdout).strip() or "valor no reconocido"))
    return value


def static_default(name):
    """Return a simple ``NAME=value`` setting of /etc/default/koha-common, or None; never source the file."""
    if not os.path.isfile(DEFAULTS_FILE):
        return None
    try:
        with open(DEFAULTS_FILE, "r", encoding="utf-8") as stream:
            lines = stream.readlines()
    except OSError as exc:
        raise ServiceError("no se pudo leer %s: %s" % (DEFAULTS_FILE, exc))
    value = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or name not in stripped:
            continue
        match = re.fullmatch(r"(?:export\s+)?%s\s*=\s*(.*?)\s*" % re.escape(name), stripped)
        if not match:
            raise ServiceError("%s está definido de forma dinámica en %s; no se modifican servicios" % (name, DEFAULTS_FILE))
        raw = match.group(1)
        if any(token in raw for token in ("$", "`", ";", "&", "|", ">", "<")):
            raise ServiceError("%s usa expansión de shell en %s; no se modifican servicios" % (name, DEFAULTS_FILE))
        try:
            words = shlex.split(raw, comments=False, posix=True)
        except ValueError:
            raise ServiceError("%s no se puede interpretar de forma segura" % name)
        if len(words) > 1:
            raise ServiceError("%s no es un valor simple en %s" % (name, DEFAULTS_FILE))
        value = words[0] if words else ""
    return value or None
