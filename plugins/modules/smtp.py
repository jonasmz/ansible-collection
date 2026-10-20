#!/usr/bin/python
# SPDX-License-Identifier: MIT-0
"""Add a Koha SMTP server and make it the default."""

DOCUMENTATION = r'''
---
module: smtp
short_description: Agrega un servidor SMTP a Koha y lo establece como predeterminado
description:
  - Crea, si no existe, un servidor SMTP en la base de datos de la instancia y lo marca como predeterminado.
  - No modifica el servidor SMTP que Koha trae por defecto (C(smtp_server) en C(koha-conf.xml)); queda como respaldo.
  - Si otro servidor de la base de datos era el predeterminado, solo se le quita esa marca; nunca se edita ni se elimina.
  - Un servidor existente con el mismo C(name) se reconcilia con los valores indicados.
  - Requiere que C(initialize) haya completado la base de datos; nunca crea instancias ni administra un MTA.
version_added: "1.3.0"
author: Jonas MZ
requirements:
  - Koha empaquetado para Debian/Ubuntu y koha-shell.
  - Una versión de Koha con C(smtp_servers.is_default).
options:
  instance:
    description: Instancia Koha existente; no tiene alias name.
    type: str
    required: true
  server:
    description: Servidor SMTP que será el predeterminado.
    type: dict
    required: true
    suboptions:
      name:
        description: Nombre del servidor en Koha; identifica el servidor para mantener la idempotencia.
        type: str
        required: true
      host:
        description: Host SMTP.
        type: str
        required: true
      port:
        description: Puerto entre 1 y 65535.
        type: int
        default: 25
      timeout:
        description: Timeout positivo en segundos.
        type: int
        default: 120
      ssl_mode:
        description: Modo TLS; acepta mayúsculas/minúsculas y espacios externos.
        type: str
        choices: [disabled, ssl, starttls]
        default: disabled
      user_name:
        description: Usuario SMTP.
        type: str
        default: ""
      password:
        description: Contraseña SMTP.
        type: str
        no_log: true
        default: ""
      debug:
        description: Depuración SMTP.
        type: bool
        default: false
  timeout:
    description: Timeout de la llamada a koha-shell, en segundos.
    type: int
    default: 120
'''

EXAMPLES = r'''
- name: SMTP con STARTTLS como predeterminado
  jmz.koha.smtp:
    instance: biblioteca
    server:
      name: Notificaciones
      host: smtp.example.org
      port: 587
      ssl_mode: starttls
      user_name: notificaciones@example.org
      password: "{{ vault_smtp_password }}"
  become: true
  no_log: true

- name: SMTP con SSL
  jmz.koha.smtp:
    instance: biblioteca
    server: {name: Notificaciones, host: smtp.example.org, port: 465, ssl_mode: ssl}
  become: true

- name: Previsualizar cambios
  jmz.koha.smtp:
    instance: biblioteca
    server: {name: Notificaciones, host: smtp.example.org, port: 587, ssl_mode: starttls}
  become: true
  check_mode: true
  diff: true
'''

RETURN = r'''
instance: {description: Instancia Koha., returned: always, type: str}
server_id: {description: Identificador del servidor en Koha; nulo en check mode si se crearía., returned: always, type: int}
created: {description: Si se creó el servidor., returned: always, type: bool}
updated: {description: Si se actualizaron los valores de un servidor existente., returned: always, type: bool}
promoted: {description: Si el servidor pasó a ser el predeterminado., returned: always, type: bool}
previous_default: {description: Servidor de la base de datos que dejó de ser predeterminado, con id y name., returned: when replaced, type: dict}
before: {description: Estado previo del servidor, sin contraseña., returned: always, type: dict}
after: {description: Estado resultante del servidor, sin contraseña., returned: always, type: dict}
'''

import ipaddress
import json
import os
import pwd
import re
import stat
import subprocess

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import choice_normalizer


PROTOCOL = 1
INSTANCE_RE = re.compile(r"^[a-z][a-z0-9-]{0,10}$")
HELPER_RE = re.compile(r"^/tmp/ansible-koha-smtp-[0-9a-f]{32}/smtp\.pl$")
LABEL_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?")
SSL_MODES = ["disabled", "ssl", "starttls"]
OUTPUT_LIMIT = 6000


class SmtpError(Exception):
    pass


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _validate(params):
    instance = params["instance"]
    if not INSTANCE_RE.fullmatch(instance):
        raise SmtpError("instance debe tener 1-11 caracteres: minúsculas, números o guiones; debe comenzar por letra")
    server = params["server"]
    name = server["name"]
    if not name.strip() or len(name) > 80 or any(c in name for c in "\r\n\x00"):
        raise SmtpError("server.name debe ser un texto de hasta 80 caracteres, sin saltos de línea ni NUL")
    host = server["host"]
    try:
        ipaddress.ip_address(host.strip("[]"))
        valid_host = True
    except ValueError:
        labels = host.rstrip(".").split(".")
        valid_host = bool(host and len(host) <= 253 and all(
            label and len(label) <= 63 and LABEL_RE.fullmatch(label) for label in labels))
    if not valid_host:
        raise SmtpError("server.host debe ser un hostname DNS o una IP válida")
    if not _is_int(server["port"]) or not 1 <= server["port"] <= 65535:
        raise SmtpError("server.port debe estar entre 1 y 65535")
    if not _is_int(server["timeout"]) or server["timeout"] <= 0:
        raise SmtpError("server.timeout debe ser positivo")
    if server["ssl_mode"] not in SSL_MODES:
        raise SmtpError("server.ssl_mode debe ser disabled, ssl o starttls")
    for key in ("user_name", "password"):
        if any(c in server[key] for c in "\r\n\x00"):
            raise SmtpError("server.%s no admite saltos de línea ni NUL" % key)
    if params["timeout"] <= 0:
        raise SmtpError("timeout debe ser positivo")


def _read_protocol(command, request, timeout):
    """Run the Perl helper with JSON on stdin and require a complete protocol response."""
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        stdout, stderr = process.communicate(json.dumps(request, separators=(",", ":")).encode("utf-8"),
                                             timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, 15)
            process.communicate(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, 9)
            except OSError:
                pass
        raise SmtpError("koha-shell excedió el límite de %s segundos" % timeout)
    except OSError as exc:
        raise SmtpError("no se pudo ejecutar koha-shell: %s" % exc)
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, TypeError, ValueError):
        raise SmtpError("el helper Perl no devolvió JSON válido (rc=%s): %s"
                        % (process.returncode, stderr.decode("utf-8", "replace")[:OUTPUT_LIMIT]))
    if not isinstance(payload, dict) or payload.get("protocol") != PROTOCOL or not isinstance(payload.get("ok"), bool):
        raise SmtpError("el helper Perl devolvió un protocolo incompleto o incompatible")
    if process.returncode != 0 or not payload["ok"]:
        raise SmtpError((payload.get("error") or {}).get("message", "falló la operación de Koha"))
    required = ("changed", "created", "updated", "promoted", "before", "after")
    if (any(key not in payload for key in required)
            or any(not isinstance(payload[key], bool) for key in required[:4])
            or not isinstance(payload["after"], dict)):
        raise SmtpError("el helper Perl devolvió una respuesta JSON incompleta o mal formada")
    return payload


def main():
    module = AnsibleModule(
        argument_spec=dict(
            instance=dict(type="str", required=True),
            server=dict(type="dict", required=True, options=dict(
                name=dict(type="str", required=True),
                host=dict(type="str", required=True),
                port=dict(type="int", default=25),
                timeout=dict(type="int", default=120),
                ssl_mode=dict(type=choice_normalizer(SSL_MODES), choices=SSL_MODES, default="disabled"),
                user_name=dict(type="str", default=""),
                password=dict(type="str", default="", no_log=True),
                debug=dict(type="bool", default=False),
            )),
            timeout=dict(type="int", default=120),
            _smtp_helper=dict(type="path", required=True, no_log=True),
        ), supports_check_mode=True,
    )
    p = module.params
    instance = p["instance"]
    try:
        _validate(p)
        if os.geteuid() != 0:
            raise SmtpError("Ejecute con become: true para usar koha-shell con los permisos de Koha")
        conf = "/etc/koha/sites/%s/koha-conf.xml" % instance
        if not os.path.isfile(conf) or not os.access(conf, os.R_OK):
            raise SmtpError("No existe una configuración legible para la instancia '%s'" % instance)
        try:
            pwd.getpwnam(instance + "-koha")
        except KeyError:
            raise SmtpError("La instancia Koha '%s' no existe (falta su usuario de sistema)" % instance)
        helper_arg = p["_smtp_helper"]
        helper = os.path.realpath(helper_arg)
        if (os.path.islink(helper_arg) or helper != helper_arg or not os.path.isfile(helper)
                or not HELPER_RE.fullmatch(helper) or not os.stat(helper).st_mode & stat.S_IRUSR):
            raise SmtpError("No se encontró el helper temporal smtp.pl de la colección")
        koha_shell = module.get_bin_path("koha-shell", required=False)
        if not koha_shell:
            raise SmtpError("koha-shell no está disponible en el host administrado")
        desired = dict(p["server"])
        desired["debug"] = 1 if desired["debug"] else 0
        # Staging path is generated by the collection action plugin and restricted above.
        command = [koha_shell, instance, "-c", "perl %s" % helper]
        request = {"protocol": PROTOCOL, "operation": "configure", "desired": desired,
                   "apply": not module.check_mode}
        payload = _read_protocol(command, request, p["timeout"])
        result = dict(instance=instance, changed=payload["changed"], server_id=payload.get("server_id"),
                      created=payload["created"], updated=payload["updated"], promoted=payload["promoted"],
                      before=payload["before"], after=payload["after"])
        if payload.get("previous_default"):
            result["previous_default"] = payload["previous_default"]
        if module._diff:
            result["diff"] = {"before": payload["before"] or {}, "after": payload["after"]}
        result["msg"] = ("Cambios SMTP proyectados." if module.check_mode and result["changed"]
                         else "El servidor SMTP ya es el predeterminado." if not result["changed"]
                         else "Servidor SMTP configurado como predeterminado.")
        module.exit_json(**result)
    except (SmtpError, OSError, ValueError, UnicodeError) as exc:
        module.fail_json(msg=str(exc), instance=instance)


if __name__ == "__main__":
    main()
