#!/usr/bin/python
# SPDX-License-Identifier: MIT-0
"""Manage the Plack daemon of one Koha instance."""

DOCUMENTATION = r'''
---
module: plack
short_description: Administra el demonio Plack de una instancia Koha y su configuración de Apache
description:
  - Usa el comando empaquetado C(koha-plack) para activar o desactivar Plack y para arrancar, detener, reiniciar o recargar el demonio.
  - C(enabled) solo descomenta o comenta los C(Include) de Plack en el sitio de Apache de la instancia; no arranca ni detiene el demonio y no recarga Apache.
  - C(state) controla el demonio de forma independiente. Mientras Plack no esté activado, la instancia sigue sirviéndose por CGI.
version_added: "1.1.0"
author: Jonas MZ
requirements:
  - Koha empaquetado para Debian/Ubuntu (C(koha-plack), C(koha-list)).
  - Módulos de Apache C(headers) y C(proxy_http) habilitados; sin ellos Apache no puede servir la instancia por Plack.
options:
  instance:
    description: Instancia Koha existente.
    type: str
    required: true
  state:
    description: Estado deseado del demonio. Si se omite o es C(status), no se toca el demonio.
    type: str
    choices: [started, stopped, restarted, reloaded, status]
  enabled:
    description: Si Plack debe estar activado en la configuración de Apache de la instancia. No puede combinarse con C(state=status).
    type: bool
  reload_apache:
    description:
      - Recarga Apache (C(graceful)) cuando esta ejecución cambió C(enabled), porque Apache solo lee los C(Include) al recargar.
      - Con C(false) el módulo devuelve C(apache_reload_required=true) y la recarga queda a cargo del playbook.
    type: bool
    default: false
  timeout:
    description: Segundos máximos de cada llamada a un comando de Koha.
    type: int
    default: 60
notes:
  - Las operaciones de cambio requieren root; use C(become=true).
'''

EXAMPLES = r'''
- name: Activar Plack, arrancarlo y recargar Apache
  jmz.koha.plack:
    instance: biblioteca
    enabled: true
    state: started
    reload_apache: true
  become: true

- name: Activar Plack y recargar Apache con un handler
  jmz.koha.plack:
    instance: biblioteca
    enabled: true
    state: started
  become: true
  notify: Reload Apache
  register: plack

- name: Recargar el demonio de forma elegante
  jmz.koha.plack:
    instance: biblioteca
    state: reloaded
  become: true

- name: Consultar sin cambiar nada
  jmz.koha.plack:
    instance: biblioteca
  register: plack_status
'''

RETURN = r'''
instance: {description: Instancia Koha., returned: always, type: str}
running: {description: "Si el demonio está activo tras la ejecución; en check mode, el proyectado.", returned: when known, type: bool}
enabled: {description: "Si Plack está activado en Apache tras la ejecución; en check mode, el proyectado.", returned: when known, type: bool}
previous_state: {description: "Estado del demonio antes de operar, C(started) o C(stopped).", returned: when known, type: str}
state: {description: "Estado del demonio resultante, C(started) o C(stopped).", returned: when known, type: str}
actions: {description: "Operaciones ejecutadas (o que se ejecutarían en check mode), en orden.", returned: always, type: list, elements: str}
apache_reload_required: {description: Verdadero si cambió C(enabled) y Apache aún no se recargó., returned: always, type: bool}
planned: {description: Verdadero en check mode., returned: always, type: bool}
diagnostics: {description: Llamadas realizadas a comandos de Koha, con salida acotada., returned: always, type: list, elements: dict}
msg: {description: Resumen del resultado., returned: always, type: str}
'''

import contextlib
import os
import re

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import choice_normalizer
from ansible_collections.jmz.koha.plugins.module_utils import koha_service as svc


STATES = ["started", "stopped", "restarted", "reloaded", "status"]
OPAC_INCLUDE = re.compile(r"^\s*Include /etc/koha/apache-shared-opac-plack\.conf\s*$")
INTRA_INCLUDE = re.compile(r"^\s*Include /etc/koha/apache-shared-intranet-plack\.conf\s*$")
APACHE_MODULES = (("headers_module", "headers"), ("proxy_http_module", "proxy_http"))


def inspect_enabled(instance):
    """Read the same Apache includes inspected by Koha's is_plack_enabled()."""
    config = "/etc/apache2/sites-available/%s.conf" % instance
    if not os.path.isfile(config):
        # Koha supports the extensionless site file as a legacy alternative.
        config = "/etc/apache2/sites-available/%s" % instance
    if not os.path.isfile(config):
        raise svc.ServiceError("no se encontró la configuración de Apache de la instancia %s" % instance)
    try:
        with open(config, "r", encoding="utf-8") as stream:
            lines = stream.readlines()
    except OSError as exc:
        raise svc.ServiceError("no se pudo leer %s: %s" % (config, exc))
    opac = any(OPAC_INCLUDE.match(line) for line in lines)
    intranet = any(INTRA_INCLUDE.match(line) for line in lines)
    if opac != intranet:
        raise svc.ServiceError("la configuración de Plack de %s es inconsistente entre OPAC e intranet" % instance)
    return opac


def apache_control(module):
    return (module.get_bin_path("apache2ctl", required=False, opt_dirs=["/usr/sbin"])
            or module.get_bin_path("apachectl", required=False, opt_dirs=["/usr/sbin"]))


def require_apache_modules(module, diagnostics, timeout):
    control = apache_control(module)
    if not control:
        raise svc.ServiceError("no se encontró apache2ctl para comprobar los módulos de Apache")
    rc, stdout, stderr = svc.run(module, [control, "-M"], diagnostics, "apache_modules", timeout)
    if rc != 0:
        raise svc.ServiceError("no se pudieron listar los módulos de Apache: %s" % svc.bounded(stderr or stdout).strip())
    missing = [name for module_name, name in APACHE_MODULES if module_name not in stdout + stderr]
    if missing:
        raise svc.ServiceError("Plack requiere los módulos de Apache %s; ejecute a2enmod %s y recargue Apache"
                               % (", ".join(missing), " ".join(missing)))


def main():
    module = AnsibleModule(
        argument_spec=dict(
            instance=dict(type="str", required=True),
            state=dict(type=choice_normalizer(STATES), choices=STATES),
            enabled=dict(type="bool"),
            reload_apache=dict(type="bool", default=False),
            timeout=dict(type="int", default=60),
        ),
        supports_check_mode=True,
    )
    p = module.params
    instance, desired_state, desired_enabled = p["instance"], p.get("state") or "status", p.get("enabled")
    diagnostics, actions = [], []
    progress = {"actions": actions, "changed": False}
    reloaded = config_changed = False
    previous = final = enabled = None
    try:
        if p["timeout"] <= 0:
            raise svc.ServiceError("timeout debe ser positivo")
        if p.get("state") == "status" and desired_enabled is not None:
            raise svc.ServiceError("state=status es de solo lectura y no puede combinarse con enabled")
        timeout = p["timeout"]
        svc.check_instance(module, instance, diagnostics, timeout)
        daemon = svc.Daemon(module, "plack", svc.find_command(module, "koha-plack"), instance, diagnostics, timeout)
        enabled = inspect_enabled(instance)
        action_enabled = None
        if desired_enabled is not None and desired_enabled != enabled:
            action_enabled = "enable" if desired_enabled else "disable"
        mutating = (desired_state != "status" or action_enabled) and not module.check_mode
        if mutating:
            svc.require_root(module)
        with svc.service_lock(instance) if mutating else contextlib.nullcontext():
            if action_enabled == "enable" or desired_state in ("started", "restarted", "reloaded"):
                require_apache_modules(module, diagnostics, timeout)
            if action_enabled:
                actions.append(action_enabled)
                progress["changed"] = config_changed = True
                if not module.check_mode:
                    rc, out, err = svc.run(module, [daemon.command, "--" + action_enabled, instance],
                                           diagnostics, action_enabled, timeout)
                    if rc != 0:
                        raise svc.ServiceError("koha-plack --%s falló para %s (rc=%s): %s"
                                               % (action_enabled, instance, rc, svc.bounded(err or out).strip()))
                    if inspect_enabled(instance) != desired_enabled:
                        raise svc.ServiceError("koha-plack --%s no dejó la configuración de Plack solicitada" % action_enabled)
                enabled = desired_enabled
            # reloaded only needs the current state; the reload itself follows.
            previous, final = svc.reconcile(daemon, "status" if desired_state == "reloaded" else desired_state,
                                            module.check_mode, progress)
            if desired_state == "reloaded":
                actions.append("reload")
                progress["changed"] = True
                if not module.check_mode:
                    daemon.operate("reload")
            if p["reload_apache"] and config_changed:
                actions.append("reload_apache")
                if not module.check_mode:
                    control = apache_control(module)
                    if not control:
                        raise svc.ServiceError("no se encontró apache2ctl para recargar Apache")
                    rc, out, err = svc.run(module, [control, "graceful"], diagnostics, "reload_apache", timeout)
                    if rc != 0:
                        raise svc.ServiceError("no se pudo recargar Apache: %s" % svc.bounded(err or out).strip())
                reloaded = True
    except svc.ServiceError as exc:
        module.fail_json(msg=str(exc), instance=instance, changed=progress["changed"], actions=actions,
                         planned=module.check_mode, diagnostics=diagnostics)
    changed = progress["changed"]
    module.exit_json(
        changed=changed, instance=instance, running=final == "started", enabled=enabled, previous_state=previous,
        state=final, actions=actions, apache_reload_required=config_changed and not reloaded,
        planned=module.check_mode, diagnostics=diagnostics,
        msg=("Plack ya está en el estado solicitado." if not changed else
             "Cambios de Plack proyectados." if module.check_mode else "Plack actualizado."))


if __name__ == "__main__":
    main()
