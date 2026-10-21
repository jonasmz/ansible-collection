#!/usr/bin/python
# SPDX-License-Identifier: MIT-0
"""Manage the Zebra server of one Koha instance."""

DOCUMENTATION = r'''
---
module: zebra
short_description: Administra el servidor Zebra de una instancia Koha
description:
  - Arranca, detiene, reinicia o consulta el servidor Zebra de una instancia con el comando empaquetado C(koha-zebra).
  - Es independiente del indexador incremental (C(jmz.koha.zebra_indexer)); no reconstruye índices ni cambia la configuración de Koha.
  - Los paquetes Debian de Koha no crean unidades systemd por instancia. El arranque al iniciar el sistema lo decide C(koha-common) para las instancias existentes, por lo que el módulo no administra una habilitación persistente.
version_added: "1.1.0"
author: Jonas MZ
requirements:
  - Koha empaquetado para Debian/Ubuntu (C(koha-zebra), C(koha-list)).
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
  verbose:
    description: Pasa C(--verbose) a las operaciones de cambio de C(koha-zebra).
    type: bool
    default: false
  timeout:
    description: Segundos máximos de cada llamada a un comando de Koha.
    type: int
    default: 60
notes:
  - Las operaciones de cambio requieren root; use C(become=true).
  - Una segunda ejecución sobre la misma instancia espera hasta 30 segundos el lock antes de fallar.
'''

EXAMPLES = r'''
- name: Zebra en marcha
  jmz.koha.zebra:
    instance: biblioteca
    state: started
  become: true

- name: Reiniciar Zebra
  jmz.koha.zebra:
    instance: biblioteca
    state: restarted
  become: true

- name: Consultar sin cambiar nada
  jmz.koha.zebra:
    instance: biblioteca
  register: zebra_status
'''

RETURN = r'''
instance: {description: Instancia Koha., returned: always, type: str}
previous_state: {description: "Estado observado antes de operar, C(started) o C(stopped).", returned: when known, type: str}
state: {description: "Estado resultante; en check mode, el proyectado.", returned: when known, type: str}
actions: {description: "Operaciones ejecutadas (o que se ejecutarían en check mode), en orden.", returned: always, type: list, elements: str}
planned: {description: Verdadero en check mode, donde C(state) es proyectado., returned: always, type: bool}
diagnostics: {description: Llamadas realizadas a comandos de Koha, con salida acotada., returned: always, type: list, elements: dict}
msg: {description: Resumen del resultado., returned: always, type: str}
'''

import contextlib

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import choice_normalizer
from ansible_collections.jmz.koha.plugins.module_utils import koha_service as svc


def main():
    module = AnsibleModule(
        argument_spec=dict(
            instance=dict(type="str", required=True),
            state=dict(type=choice_normalizer(svc.STATES), choices=svc.STATES, default="status"),
            verbose=dict(type="bool", default=False),
            timeout=dict(type="int", default=60),
        ),
        supports_check_mode=True,
    )
    p = module.params
    instance, desired = p["instance"], p["state"]
    diagnostics = []
    progress = {"actions": [], "changed": False}
    previous = final = None
    try:
        if p["timeout"] <= 0:
            raise svc.ServiceError("timeout debe ser positivo")
        svc.check_instance(module, instance, diagnostics, p["timeout"])
        daemon = svc.Daemon(module, "zebra", svc.find_command(module, "koha-zebra"), instance, diagnostics,
                            p["timeout"], operation_flags=["--verbose"] if p["verbose"] else [])
        mutating = desired != "status" and not module.check_mode
        if mutating:
            svc.require_root(module)
        with svc.service_lock(instance) if mutating else contextlib.nullcontext():
            previous, final = svc.reconcile(daemon, desired, module.check_mode, progress)
    except svc.ServiceError as exc:
        module.fail_json(msg=str(exc), instance=instance, changed=progress["changed"], previous_state=previous,
                         actions=progress["actions"], planned=module.check_mode, diagnostics=diagnostics)
    changed = progress["changed"]
    module.exit_json(
        changed=changed, instance=instance, previous_state=previous, state=final, actions=progress["actions"],
        planned=module.check_mode, diagnostics=diagnostics,
        msg=("Zebra ya está en el estado solicitado." if not changed else
             "Cambios de Zebra proyectados." if module.check_mode else "Zebra actualizado."))


if __name__ == "__main__":
    main()
