# SPDX-License-Identifier: MIT-0
#!/usr/bin/python
"""Manage Koha background job workers."""

DOCUMENTATION = r'''
---
module: worker
short_description: Administra los workers de background jobs de Koha
description:
  - Gestiona los workers de una instancia mediante el comando oficial C(koha-worker).
  - Admite las colas C(default), C(long_tasks) y la abstracción C(all).
  - El estado de ejecución y la habilitación al inicio son propiedades independientes.
version_added: "1.2.0"
author: Jonas MZ
requirements:
  - Koha instalado mediante sus paquetes Debian o Ubuntu en el host administrado
  - koha-worker disponible en el host administrado
options:
  name:
    description: Identificador de la instancia Koha.
    type: str
    required: true
  state:
    description: Estado operativo deseado. C(status) solo consulta.
    type: str
    choices: [started, stopped, restarted, status]
    default: status
  queue:
    description: Cola individual o C(all) para ambas colas conocidas.
    type: str
    choices: [default, long_tasks, all]
    default: default
  enabled:
    description: Habilitación persistente al inicio; no cambia el estado de ejecución.
    type: bool
  quiet:
    description: Pasa C(--quiet) a koha-worker cuando la opción está disponible.
    type: bool
    default: false
notes:
  - C(enabled) solo está disponible cuando existen las unidades systemd y Koha anuncia C(--enable) y C(--disable).
  - Las instalaciones SysV admiten el ciclo de vida, pero no una habilitación persistente gestionable por este módulo.
  - C(state=status) no puede combinarse con un valor explícito de C(enabled).
  - Las operaciones de cambio requieren privilegios de root; normalmente se usa C(become: true).
  - La versión instalada determina las capacidades disponibles; el módulo las consulta en tiempo de ejecución.
'''

EXAMPLES = r'''
- name: Iniciar el worker general
  jmz.koha.worker:
    name: biblioteca
    state: started
    queue: default
  become: true

- name: Asegurar ambas colas y su inicio automático
  jmz.koha.worker:
    name: biblioteca
    state: started
    queue: all
    enabled: true
  become: true

- name: Reiniciar los workers
  jmz.koha.worker:
    name: biblioteca
    state: restarted
    queue: all
  become: true

- name: Consultar los workers
  jmz.koha.worker:
    name: biblioteca
    state: status
    queue: all
  register: worker_status

- name: Detener y deshabilitar los workers
  jmz.koha.worker:
    name: biblioteca
    state: stopped
    queue: all
    enabled: false
  become: true
'''

RETURN = r'''
changed:
  description: Si se modificó alguna cola o se ejecutó un reinicio explícito.
  returned: always
  type: bool
name:
  description: Identificador de la instancia.
  returned: always
  type: str
state:
  description: Estado solicitado.
  returned: always
  type: str
queue:
  description: Cola solicitada.
  returned: always
  type: str
backend:
  description: Backend detectado, C(systemd) o C(sysv).
  returned: success
  type: str
workers:
  description: Estado observado por cola. C(running) y C(enabled) pueden ser nulos cuando no aplican.
  returned: success
  type: dict
  contains:
    running:
      description: Si el worker está activo.
      type: bool
    enabled:
      description: Si la unidad está habilitada al inicio; nulo en SysV o si el estado no es aplicable.
      type: bool
    changed:
      description: Si esta cola cambió en la invocación.
      type: bool
    status:
      description: Estado observado (C(running), C(stopped) o C(failed)); ausencias o ambigüedades producen error.
      type: str
actions:
  description: Operaciones Koha ejecutadas o planificadas.
  returned: always
  type: list
msg:
  description: Resumen del resultado.
  returned: always
  type: str
diff:
  description: Transiciones solicitadas, sin datos sensibles.
  returned: when diff mode is enabled
  type: dict
failures:
  description: Acciones fallidas o colas cuyo estado final no coincidió con lo solicitado.
  returned: on operational failure
  type: list
'''

import os
import re

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import choice_normalizer


NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,10}$")
QUEUES = ("default", "long_tasks")
UNIT_FILE_STATES_ENABLED = {"enabled", "enabled-runtime", "linked", "linked-runtime", "alias"}
UNIT_FILE_STATES_DISABLED = {"disabled"}


class WorkerError(Exception):
    """A validation, compatibility, or operation error with context."""


def _systemd_show(module, systemctl, unit):
    rc, stdout, stderr = module.run_command(
        [systemctl, "show", "--no-pager", "--property=LoadState,ActiveState,SubState,UnitFileState", unit]
    )
    values = {}
    for line in stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return rc, values, stdout, stderr


def _unit_name(name, queue):
    if queue == "default":
        return "koha-worker@%s.service" % name
    return "koha-worker-%s@%s.service" % (queue, name)


def _inspect_systemd(module, systemctl, name, queues):
    observed = {}
    for queue in queues:
        unit = _unit_name(name, queue)
        rc, values, stdout, stderr = _systemd_show(module, systemctl, unit)
        if rc != 0 and values.get("LoadState") != "not-found":
            raise WorkerError("No se pudo consultar la unidad %s (rc=%s): %s" %
                              (unit, rc, (stderr or stdout).strip()))
        if values.get("LoadState") == "not-found" or not values.get("LoadState"):
            observed[queue] = {"unit": unit, "missing": True, "running": None, "enabled": None,
                               "status": "missing", "raw": stdout + stderr}
            continue
        active = values.get("ActiveState")
        if active == "active":
            running, status = True, "running"
        elif active == "inactive":
            running, status = False, "stopped"
        elif active == "failed":
            running, status = False, "failed"
        else:
            raise WorkerError("Estado systemd no interpretable para %s: ActiveState=%r SubState=%r" %
                              (unit, active, values.get("SubState")))
        unit_file_state = values.get("UnitFileState", "").lower()
        if unit_file_state in UNIT_FILE_STATES_ENABLED:
            enabled = True
        elif unit_file_state in UNIT_FILE_STATES_DISABLED:
            enabled = False
        else:
            enabled = None
        observed[queue] = {"unit": unit, "missing": False, "running": running, "enabled": enabled,
                           "status": status, "unit_file_state": unit_file_state}
    return observed


def _inspect_sysv(module, binary, name, queues, quiet):
    observed = {}
    for queue in queues:
        argv = [binary, "--status", "--queue", queue]
        if quiet:
            argv.append("--quiet")
        argv.append(name)
        rc, stdout, stderr = module.run_command(argv)
        output = "%s\n%s" % (stdout, stderr)
        expected = re.escape(name) + r"\s*\(" + re.escape(queue) + r"\)"
        if re.search(r"worker running for\s+" + expected, output, re.IGNORECASE):
            running, status = True, "running"
        elif re.search(r"worker not running for\s+" + expected, output, re.IGNORECASE):
            running, status = False, "stopped"
        else:
            raise WorkerError("koha-worker --status no permitió determinar el estado de %s (%s; rc=%s): %s" %
                              (name, queue, rc, output.strip() or "sin salida"))
        observed[queue] = {"unit": None, "missing": False, "running": running, "enabled": None,
                           "status": status}
    return observed


def _command(module, binary, action, name, queues, use_all, quiet):
    argv = [binary, "--" + action]
    if use_all:
        argv.append("--all-queues")
    else:
        argv.extend(["--queue", queues[0]])
    if quiet:
        argv.append("--quiet")
    argv.append(name)
    return module.run_command(argv)


def _display_worker(item, changed):
    return {"running": item.get("running"), "enabled": item.get("enabled"),
            "changed": changed, "status": item.get("status", "unknown")}


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type="str", required=True),
            state=dict(type=choice_normalizer(["started", "stopped", "restarted", "status"]), choices=["started", "stopped", "restarted", "status"], default="status"),
            queue=dict(type=choice_normalizer(["default", "long_tasks", "all"]), choices=["default", "long_tasks", "all"], default="default"),
            enabled=dict(type="bool"),
            quiet=dict(type="bool", default=False),
        ),
        supports_check_mode=True,
    )
    name = module.params["name"]
    desired_state = module.params["state"]
    requested_queue = module.params["queue"]
    desired_enabled = module.params.get("enabled")
    quiet = module.params["quiet"]

    if not NAME_RE.fullmatch(name or ""):
        module.fail_json(
            msg=("name debe ser un identificador Koha válido (1-11 caracteres, minúsculas, "
                 "dígitos o guiones; debe comenzar con una letra)"),
            name=name,
        )
    if desired_state == "status" and desired_enabled is not None:
        module.fail_json(msg="state=status es de solo lectura y no puede combinarse con enabled", name=name)

    config_path = "/etc/koha/sites/%s/koha-conf.xml" % name
    instance_path = "/etc/koha/sites/%s" % name
    if not os.path.isdir(instance_path) or not os.path.isfile(config_path):
        module.fail_json(msg="La instancia Koha %s no existe o no tiene koha-conf.xml" % name, name=name)
    binary = module.get_bin_path("koha-worker", required=False)
    if not binary:
        module.fail_json(msg="No se encontró koha-worker en el host administrado", name=name)

    help_rc, help_out, help_err = module.run_command([binary, "--help"])
    help_text = help_out + "\n" + help_err
    if help_rc != 0 or "--status" not in help_text or "--queue" not in help_text:
        module.fail_json(msg="No se pudo verificar la interfaz requerida de koha-worker --help", name=name,
                         rc=help_rc, stderr=help_err)
    supports_all = "--all-queues" in help_text
    supports_quiet = "--quiet" in help_text or "-q" in help_text
    if requested_queue == "all" and not supports_all:
        # The module can still address both queues independently.
        queues = list(QUEUES)
    else:
        queues = list(QUEUES) if requested_queue == "all" else [requested_queue]
    if quiet and not supports_quiet:
        module.fail_json(msg="La versión instalada de koha-worker no anuncia soporte para --quiet", name=name)
    if desired_state in ("started", "stopped", "restarted") and ("--" + {
            "started": "start", "stopped": "stop", "restarted": "restart"}[desired_state]) not in help_text:
        module.fail_json(msg="La versión instalada de koha-worker no anuncia la operación solicitada", name=name,
                         state=desired_state)
    if desired_enabled is not None and ("--enable" not in help_text or "--disable" not in help_text):
        module.fail_json(msg="La versión instalada de koha-worker no anuncia --enable y --disable", name=name)

    # Koha's packaged per-worker templates are the positive signal for its
    # systemd backend. A generic systemd PID 1 can also host the legacy Koha
    # daemon backend, so /run/systemd/system alone is not sufficient.
    systemctl = module.get_bin_path("systemctl", required=False)
    systemd_templates = (
        "/lib/systemd/system/koha-worker@.service",
        "/usr/lib/systemd/system/koha-worker@.service",
        "/etc/systemd/system/koha-worker@.service",
        "/lib/systemd/system/koha-worker-long_tasks@.service",
        "/usr/lib/systemd/system/koha-worker-long_tasks@.service",
        "/etc/systemd/system/koha-worker-long_tasks@.service",
    )
    systemd_backend = bool(systemctl) and any(os.path.isfile(path) for path in systemd_templates)
    observed = {}
    backend = "unknown"
    actions = []
    applied = []
    changed_queues = set()
    try:
        if systemd_backend:
            backend = "systemd"
            observed = _inspect_systemd(module, systemctl, name, queues)
            if all(item["missing"] for item in observed.values()):
                raise WorkerError("systemd está activo, pero no existen las unidades Koha esperadas: %s" %
                                  ", ".join(_unit_name(name, q) for q in queues))
            missing = [q for q, item in observed.items() if item["missing"]]
            if missing:
                raise WorkerError("Faltan unidades systemd para las colas solicitadas: %s" % ", ".join(missing))
        else:
            backend = "sysv"
            observed = _inspect_sysv(module, binary, name, queues, quiet)
        if desired_enabled is not None and backend != "systemd":
            raise WorkerError("enabled no se puede gestionar de forma persistente y verificable con el backend SysV")
        if desired_enabled is not None:
            unknown_enabled = [q for q in queues if observed[q]["enabled"] is None]
            if unknown_enabled:
                raise WorkerError("No se pudo determinar UnitFileState de las unidades: %s" %
                                  ", ".join(unknown_enabled))

        pending = []
        if desired_enabled is not None:
            pending = [q for q in queues if observed[q]["enabled"] != desired_enabled]
        lifecycle = []
        if desired_state == "started":
            lifecycle = [q for q in queues if observed[q]["running"] is False]
        elif desired_state == "stopped":
            lifecycle = [q for q in queues if observed[q]["running"] is True]
        elif desired_state == "restarted":
            lifecycle = list(queues)

        planned = []
        before = {q: {"running": observed[q].get("running"), "enabled": observed[q].get("enabled")}
                  for q in queues}
        if pending:
            planned.append({"action": "enable" if desired_enabled else "disable", "queues": pending})
        if desired_state == "restarted":
            planned.append({"action": "restart", "queues": list(lifecycle)})
        elif lifecycle:
            planned.append({"action": "start" if desired_state == "started" else "stop", "queues": list(lifecycle)})

        if not module.check_mode and planned and os.geteuid() != 0:
            raise WorkerError("Se requieren privilegios de root para cambiar el ciclo de vida o habilitación; "
                              "use become: true")

        for plan in planned:
            action = plan["action"]
            action_queues = plan["queues"]
            if not action_queues:
                continue
            use_all = requested_queue == "all" and supports_all and set(action_queues) == set(QUEUES)
            if module.check_mode:
                actions.append({"action": action, "queues": action_queues, "planned": True})
                changed_queues.update(action_queues)
                if action == "enable":
                    for q in action_queues:
                        observed[q]["enabled"] = True
                elif action == "disable":
                    for q in action_queues:
                        observed[q]["enabled"] = False
                else:
                    for q in action_queues:
                        observed[q]["running"] = action != "stop"
                        observed[q]["status"] = "stopped" if action == "stop" else "running"
                continue
            rc, stdout, stderr = _command(module, binary, action, name, action_queues, use_all, quiet)
            actions.append({"action": action, "queues": action_queues, "planned": False, "rc": rc})
            if action == "restart":
                changed_queues.update(action_queues)
            # koha-worker has historically returned zero after some operational errors.
            # Always inspect each affected service after the official action.
            if rc != 0:
                applied.append({"action": action, "queues": action_queues, "rc": rc,
                                "stderr": stderr.strip(), "stdout": stdout.strip()})
            if action in ("enable", "disable"):
                for q in action_queues:
                    refreshed = _inspect_systemd(module, systemctl, name, [q])
                    observed[q].update(refreshed[q])
                    if before[q]["enabled"] != observed[q]["enabled"]:
                        changed_queues.add(q)
                    if observed[q]["enabled"] != (action == "enable"):
                        raise WorkerError("La operación --%s no estableció la habilitación solicitada para %s" %
                                          (action, q))
            else:
                for q in action_queues:
                    if backend == "systemd":
                        refreshed = _inspect_systemd(module, systemctl, name, [q])
                    else:
                        refreshed = _inspect_sysv(module, binary, name, [q], quiet)
                    observed[q].update(refreshed[q])
                    expected_running = action != "stop"
                    if action == "restart" or before[q]["running"] != observed[q]["running"]:
                        changed_queues.add(q)
                    if observed[q]["running"] != expected_running:
                        applied.append({"action": action, "queue": q, "status": observed[q]["status"],
                                        "stdout": stdout.strip(), "stderr": stderr.strip(), "rc": rc})
                        continue
            if rc != 0 or any(entry.get("action") == action and entry.get("rc") == rc for entry in applied):
                raise WorkerError("koha-worker --%s falló para una o más colas" % action)

        worker_results = {q: _display_worker(observed[q], q in changed_queues) for q in queues}
        changed = bool(changed_queues)
        if desired_state == "restarted" and not module.check_mode:
            changed = True
            for q in queues:
                worker_results[q]["changed"] = True
        message = ("Se planificaron cambios para las colas seleccionadas." if module.check_mode and changed else
                   "Los workers seleccionados están activos." if desired_state == "started" else
                   "Los workers seleccionados están detenidos." if desired_state == "stopped" else
                   "Se reiniciaron los workers seleccionados." if desired_state == "restarted" else
                   "Estado de los workers consultado sin cambios.")
        result = dict(changed=changed, name=name, state=desired_state, queue=requested_queue,
                      backend=backend, workers=worker_results, actions=actions, msg=message)
        if getattr(module, "_diff", False):
            result["diff"] = {"before": before,
                              "after": {q: {"running": worker_results[q]["running"],
                                            "enabled": worker_results[q]["enabled"]} for q in queues}}
        module.exit_json(**result)
    except WorkerError as exc:
        current = {q: _display_worker(observed.get(q, {}), q in changed_queues)
                   for q in queues if q in observed}
        module.fail_json(msg=str(exc), name=name, state=desired_state, queue=requested_queue,
                         backend=backend, workers=current, changed=bool(changed_queues),
                         actions=actions, failures=applied)


if __name__ == "__main__":
    main()
