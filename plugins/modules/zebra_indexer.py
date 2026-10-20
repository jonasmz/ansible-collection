#!/usr/bin/python
# SPDX-License-Identifier: MIT-0
"""Manage the incremental Zebra indexer daemon of one Koha instance."""

DOCUMENTATION = r'''
---
module: zebra_indexer
short_description: Administra el indexador incremental de Zebra de una instancia Koha
description:
  - Arranca, detiene, reinicia o consulta el demonio del indexador con el comando empaquetado C(koha-indexer).
  - Es independiente del servidor Zebra (C(jmz.koha.zebra)); no reconstruye índices, no administra Elasticsearch ni cambia la configuración de Koha.
  - Los paquetes Debian de Koha no crean unidades systemd por instancia. El arranque al iniciar el sistema lo decide C(koha-common) según C(USE_INDEXER_DAEMON), por lo que el módulo no administra una habilitación persistente.
version_added: "1.2.0"
author: Jonas MZ
requirements:
  - Koha empaquetado para Debian/Ubuntu (C(koha-indexer), C(koha-list)).
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
  quiet:
    description: Pasa C(--quiet) a las operaciones de cambio de C(koha-indexer).
    type: bool
    default: false
  verify_zebra_engine:
    description:
      - Comprueba la preferencia C(SearchEngine) con C(koha-shell) antes de arrancar o reiniciar.
      - Solo permite arrancar o reiniciar cuando vale C(Zebra). Una consulta fallida es un error; parar y consultar siguen disponibles.
    type: bool
    default: false
  require_zebra_running:
    description:
      - Exige que el servidor Zebra de la misma instancia esté activo antes de arrancar o reiniciar el indexador.
      - Es una comprobación de solo lectura; este módulo nunca arranca Zebra.
    type: bool
    default: false
  timeout:
    description: Segundos máximos de cada llamada a un comando de Koha.
    type: int
    default: 60
notes:
  - Las operaciones de cambio requieren root; use C(become=true).
  - Si C(ALTERNATE_INDEXER_DAEMON) está definido en C(/etc/default/koha-common), el módulo se niega a cambiar el estado porque el demonio podría no ser el indexador de Zebra.
'''

EXAMPLES = r'''
- name: Indexador en marcha
  jmz.koha.zebra_indexer:
    instance: biblioteca
    state: started
  become: true

- name: Arrancar solo si el motor es Zebra y su servidor está activo
  jmz.koha.zebra_indexer:
    instance: biblioteca
    state: started
    verify_zebra_engine: true
    require_zebra_running: true
  become: true

- name: Consultar sin cambiar nada
  jmz.koha.zebra_indexer:
    instance: biblioteca
  register: indexer_status
'''

RETURN = r'''
instance: {description: Instancia Koha., returned: always, type: str}
previous_state: {description: "Estado observado antes de operar, C(started) o C(stopped).", returned: when known, type: str}
state: {description: "Estado resultante; en check mode, el proyectado.", returned: when known, type: str}
search_engine: {description: Valor de C(SearchEngine) si se pidió verificarlo., returned: when verified, type: str}
zebra_running: {description: Si el servidor Zebra estaba activo, si se pidió comprobarlo., returned: when checked, type: bool}
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
            quiet=dict(type="bool", default=False),
            verify_zebra_engine=dict(type="bool", default=False),
            require_zebra_running=dict(type="bool", default=False),
            timeout=dict(type="int", default=60),
        ),
        supports_check_mode=True,
    )
    p = module.params
    instance, desired = p["instance"], p["state"]
    diagnostics = []
    progress = {"actions": [], "changed": False}
    previous = final = engine = zebra_running = None
    try:
        if p["timeout"] <= 0:
            raise svc.ServiceError("timeout debe ser positivo")
        timeout = p["timeout"]
        svc.check_instance(module, instance, diagnostics, timeout)
        daemon = svc.Daemon(module, "indexador", svc.find_command(module, "koha-indexer"), instance, diagnostics,
                            timeout, operation_flags=["--quiet"] if p["quiet"] else [])
        starting = desired in ("started", "restarted")
        if p["verify_zebra_engine"]:
            engine = svc.search_engine(module, instance, diagnostics, timeout)
            if starting and engine != "Zebra":
                raise svc.ServiceError("no se arranca el indexador de Zebra de %s: SearchEngine es %s" % (instance, engine))
        if p["require_zebra_running"] and starting:
            zebra = svc.Daemon(module, "zebra", svc.find_command(module, "koha-zebra"), instance, diagnostics, timeout)
            zebra_running = zebra.status() == "started"
            if not zebra_running:
                raise svc.ServiceError("Zebra está detenido para %s; arránquelo con jmz.koha.zebra antes del indexador" % instance)
        mutating = desired != "status" and not module.check_mode
        if mutating:
            svc.require_root(module)
        with svc.service_lock(instance) if mutating else contextlib.nullcontext():
            if svc.plan(desired, daemon.status()) and svc.static_default("ALTERNATE_INDEXER_DAEMON"):
                raise svc.ServiceError(
                    "no se modifica el indexador de %s: ALTERNATE_INDEXER_DAEMON selecciona otro demonio" % instance)
            previous, final = svc.reconcile(daemon, desired, module.check_mode, progress)
    except svc.ServiceError as exc:
        module.fail_json(msg=str(exc), instance=instance, changed=progress["changed"], previous_state=previous,
                         actions=progress["actions"], planned=module.check_mode, diagnostics=diagnostics)
    result = dict(changed=progress["changed"], instance=instance, previous_state=previous, state=final,
                  actions=progress["actions"], planned=module.check_mode, diagnostics=diagnostics)
    if engine is not None:
        result["search_engine"] = engine
    if zebra_running is not None:
        result["zebra_running"] = zebra_running
    result["msg"] = ("El indexador ya está en el estado solicitado." if not result["changed"] else
                     "Cambios del indexador proyectados." if module.check_mode else "Indexador actualizado.")
    module.exit_json(**result)


if __name__ == "__main__":
    main()
