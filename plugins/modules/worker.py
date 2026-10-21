#!/usr/bin/python
# SPDX-License-Identifier: MIT-0
"""Manage Koha background job workers."""

DOCUMENTATION = r'''
---
module: worker
short_description: Administra los workers de background jobs de Koha
description:
  - Arranca, detiene, reinicia o consulta los workers de una instancia con el comando empaquetado C(koha-worker).
  - Admite las colas C(default) y C(long_tasks), o ambas con C(all).
  - Los paquetes Debian de Koha no crean unidades systemd por instancia. El arranque al iniciar el sistema lo decide C(koha-common), por lo que el módulo no administra una habilitación persistente.
version_added: "1.2.0"
author: Jonas MZ
requirements:
  - Koha empaquetado para Debian/Ubuntu (C(koha-worker), C(koha-list)).
options:
  instance:
    description: Instancia Koha existente.
    type: str
    required: true
  state:
    description: Estado deseado. C(status) solo consulta.
    type: str
    choices: [started, stopped, restarted, status]
    default: status
  queue:
    description: Cola individual, o C(all) para ambas.
    type: str
    choices: [default, long_tasks, all]
    default: default
  quiet:
    description: Pasa C(--quiet) a las operaciones de cambio de C(koha-worker).
    type: bool
    default: false
  timeout:
    description: Segundos máximos de cada llamada a un comando de Koha.
    type: int
    default: 60
notes:
  - Las operaciones de cambio requieren root; use C(become=true).
  - Cada cola se gestiona por separado, de modo que una cola ya en el estado pedido no se toca.
'''

EXAMPLES = r'''
- name: Ambas colas en marcha
  jmz.koha.worker:
    instance: biblioteca
    queue: all
    state: started
  become: true

- name: Reiniciar el worker general
  jmz.koha.worker:
    instance: biblioteca
    state: restarted
  become: true

- name: Consultar ambas colas
  jmz.koha.worker:
    instance: biblioteca
    queue: all
  register: worker_status
'''

RETURN = r'''
instance: {description: Instancia Koha., returned: always, type: str}
queue: {description: Cola solicitada., returned: always, type: str}
workers:
  description: "Estado por cola: C(previous_state), C(state) (proyectado en check mode) y C(changed)."
  returned: when known
  type: dict
actions:
  description: "Operaciones ejecutadas (o que se ejecutarían en check mode) con el formato C(operación:cola)."
  returned: always
  type: list
  elements: str
planned: {description: Verdadero en check mode, donde C(state) es proyectado., returned: always, type: bool}
diagnostics: {description: Llamadas realizadas a comandos de Koha, con salida acotada., returned: always, type: list, elements: dict}
msg: {description: Resumen del resultado., returned: always, type: str}
'''

import contextlib

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import choice_normalizer
from ansible_collections.jmz.koha.plugins.module_utils import koha_service as svc


QUEUES = ["default", "long_tasks"]


def main():
    queue_choices = QUEUES + ["all"]
    module = AnsibleModule(
        argument_spec=dict(
            instance=dict(type="str", required=True),
            state=dict(type=choice_normalizer(svc.STATES), choices=svc.STATES, default="status"),
            queue=dict(type=choice_normalizer(queue_choices), choices=queue_choices, default="default"),
            quiet=dict(type="bool", default=False),
            timeout=dict(type="int", default=60),
        ),
        supports_check_mode=True,
    )
    p = module.params
    instance, desired, requested = p["instance"], p["state"], p["queue"]
    queues = QUEUES if requested == "all" else [requested]
    diagnostics = []
    progress = {"actions": [], "changed": False}
    workers = {}
    try:
        if p["timeout"] <= 0:
            raise svc.ServiceError("timeout debe ser positivo")
        svc.check_instance(module, instance, diagnostics, p["timeout"])
        command = svc.find_command(module, "koha-worker")
        daemons = {q: svc.Daemon(module, "worker (%s)" % q, command, instance, diagnostics, p["timeout"],
                                 flags=["--queue", q], operation_flags=["--quiet"] if p["quiet"] else [])
                   for q in queues}
        mutating = desired != "status" and not module.check_mode
        if mutating:
            svc.require_root(module)
        with svc.service_lock(instance) if mutating else contextlib.nullcontext():
            for queue in queues:
                queue_progress = {"actions": [], "changed": False}
                try:
                    previous, final = svc.reconcile(daemons[queue], desired, module.check_mode, queue_progress)
                finally:
                    progress["actions"].extend("%s:%s" % (a, queue) for a in queue_progress["actions"])
                    progress["changed"] = progress["changed"] or queue_progress["changed"]
                workers[queue] = dict(previous_state=previous, state=final, changed=queue_progress["changed"])
    except svc.ServiceError as exc:
        module.fail_json(msg=str(exc), instance=instance, queue=requested, changed=progress["changed"],
                         workers=workers, actions=progress["actions"], planned=module.check_mode,
                         diagnostics=diagnostics)
    module.exit_json(
        changed=progress["changed"], instance=instance, queue=requested, workers=workers,
        actions=progress["actions"], planned=module.check_mode, diagnostics=diagnostics,
        msg=("Los workers ya están en el estado solicitado." if not progress["changed"] else
             "Cambios de workers proyectados." if module.check_mode else "Workers actualizados."))


if __name__ == "__main__":
    main()
