#!/usr/bin/python
# SPDX-License-Identifier: MIT-0
"""Create a Koha staff user and set its permissions without making it a superlibrarian."""

DOCUMENTATION = r'''
---
module: user
short_description: Crea un usuario de Koha y establece sus permisos operativos
description:
  - Crea, si no existe, un usuario identificado por C(username) y reconcilia su perfil, su contraseña y sus permisos.
  - Los permisos son declarativos y exactos; los que no se listan en C(permissions) se revocan.
  - Nunca concede C(superlibrarian) y se niega a modificar a un usuario que ya sea superlibrarian.
  - Los nombres de módulos y subpermisos se validan contra Koha antes de escribir.
  - Requiere que C(initialize) haya completado la base de datos; nunca crea instancias, bibliotecas ni categorías.
version_added: "1.4.0"
author: Jonas MZ
requirements:
  - Koha empaquetado para Debian/Ubuntu y koha-shell.
  - Una versión de Koha con C(Koha::Patron->set_permissions).
options:
  instance:
    description: Instancia Koha existente.
    type: str
    required: true
  username:
    description: Identificador de acceso (C(userid)); identifica al usuario para mantener la idempotencia.
    type: str
    required: true
  password:
    description: Contraseña; debe cumplir la política de la categoría. Se reconcilia en cada ejecución.
    type: str
    required: true
    no_log: true
  surname:
    description: Apellido.
    type: str
    required: true
  firstname:
    description: Nombre. Si se omite no se modifica el de un usuario existente.
    type: str
  library:
    description: Código de una biblioteca existente.
    type: str
    required: true
  category:
    description: Código de una categoría de usuarios existente.
    type: str
    required: true
  cardnumber:
    description: Número de tarjeta. Si se omite no se modifica el de un usuario existente.
    type: str
  email:
    description: Correo electrónico. Si se omite no se modifica el de un usuario existente.
    type: str
  permissions:
    description:
      - Permisos que tendrá el usuario, por módulo de Koha (C(catalogue), C(circulate), C(tools), ...).
      - Cada valor es C(true), para todo el módulo, o una lista de subpermisos (por ejemplo C(circulate_remaining_permissions)).
      - Un valor C(false) equivale a no listar el módulo.
    type: dict
    default: {}
  timeout:
    description: Timeout, en segundos, de la llamada a koha-shell.
    type: int
    default: 120
'''

EXAMPLES = r'''
- name: Bibliotecaria de circulación y catálogo
  jmz.koha.user:
    instance: biblioteca
    username: mperez
    password: "{{ vault_mperez_password }}"
    firstname: María
    surname: Pérez
    library: CENTRAL
    category: STAFF
    email: mperez@example.org
    permissions:
      catalogue: true
      circulate: [circulate_remaining_permissions, force_checkout]
      reserveforothers: true
  become: true
  no_log: true

- name: Previsualizar cambios
  jmz.koha.user:
    instance: biblioteca
    username: mperez
    password: "{{ vault_mperez_password }}"
    surname: Pérez
    library: CENTRAL
    category: STAFF
    permissions: {catalogue: true}
  become: true
  check_mode: true
  diff: true
  no_log: true
'''

RETURN = r'''
instance: {description: Instancia Koha., returned: always, type: str}
borrowernumber: {description: Identificador del usuario en Koha; nulo en check mode si se crearía., returned: always, type: int}
created: {description: Si se creó el usuario., returned: always, type: bool}
updated: {description: Si se actualizó el perfil de un usuario existente., returned: always, type: bool}
permissions_changed: {description: Si cambiaron los permisos de un usuario existente., returned: always, type: bool}
password_changed: {description: Si cambió la contraseña de un usuario existente., returned: always, type: bool}
before: {description: "Estado previo; la contraseña es un booleano.", returned: always, type: dict}
after: {description: "Estado resultante; la contraseña es un booleano o, si esta ejecución la cambió, C(modificada).", returned: always, type: dict}
'''

import contextlib
import json
import os
import pwd
import re
import stat
import subprocess

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import NAME_RE, ModuleInputError
from ansible_collections.jmz.koha.plugins.module_utils.koha_lock import exclusive_lock


PROTOCOL = 1
HELPER_RE = re.compile(r"^/tmp/ansible-koha-user-[0-9a-f]{32}/user\.pl$")
KEY_RE = re.compile(r"[a-z][a-z0-9_]*")
OUTPUT_LIMIT = 6000


class UserError(Exception):
    def __init__(self, message, changed=False):
        super().__init__(message)
        self.changed = changed


def _plain_text(value, name, limit=80):
    if not value.strip() or len(value) > limit or any(c in value for c in "\r\n\x00"):
        raise UserError("%s debe ser un texto de hasta %d caracteres, sin saltos de línea ni NUL" % (name, limit))


def _permissions(raw):
    """Reduce the declaration to {module: True | [codes]}; Koha cannot tell a typo from a real name."""
    result = {}
    for module, value in raw.items():
        if not isinstance(module, str) or not KEY_RE.fullmatch(module):
            raise UserError("permissions: nombre de módulo inválido: %r" % (module,))
        if module == "superlibrarian":
            raise UserError("permissions no puede incluir superlibrarian; este módulo solo da permisos operativos")
        if isinstance(value, bool):
            if value:
                result[module] = True
        elif isinstance(value, list) and value and all(isinstance(c, str) and KEY_RE.fullmatch(c) for c in value):
            result[module] = sorted(set(value))
        else:
            raise UserError("permissions.%s debe ser true, false o una lista no vacía de subpermisos" % module)
    return result


def _validate(params):
    if not NAME_RE.fullmatch(params["instance"]):
        raise UserError("instance debe tener 1-11 caracteres: minúsculas, números o guiones; debe comenzar por letra")
    _plain_text(params["username"], "username", 75)
    _plain_text(params["surname"], "surname")
    for key in ("firstname", "cardnumber", "email"):
        if params[key] is not None:
            _plain_text(params[key], key, 255)
    for key in ("library", "category"):
        _plain_text(params[key], key, 10)
    if not params["password"] or any(c in params["password"] for c in "\r\n\x00"):
        raise UserError("password no puede estar vacía ni contener saltos de línea o NUL")
    if params["timeout"] <= 0:
        raise UserError("timeout debe ser positivo")


@contextlib.contextmanager
def _instance_lock(instance):
    """Serialize runs per instance so two runs cannot both create the same user."""
    try:
        with exclusive_lock("user", instance, "otra ejecución está configurando usuarios en %s; reintente cuando termine" % instance,
                            wait=30):
            yield
    except ModuleInputError as exc:
        raise UserError(str(exc))


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
        raise UserError("koha-shell excedió el límite de %s segundos; la operación es transaccional, reintente" % timeout)
    except OSError as exc:
        raise UserError("no se pudo ejecutar koha-shell: %s" % exc)
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, TypeError, ValueError):
        raise UserError("el helper Perl no devolvió JSON válido (rc=%s): %s"
                        % (process.returncode, stderr.decode("utf-8", "replace")[:OUTPUT_LIMIT]))
    if not isinstance(payload, dict) or payload.get("protocol") != PROTOCOL or not isinstance(payload.get("ok"), bool):
        raise UserError("el helper Perl devolvió un protocolo incompleto o incompatible")
    if process.returncode != 0 or not payload["ok"]:
        # "committed" means the transaction finished before a later check failed: Koha was changed.
        raise UserError((payload.get("error") or {}).get("message", "falló la operación de Koha"),
                        changed=payload.get("committed") is True)
    required = ("changed", "created", "updated", "permissions_changed", "password_changed", "before", "after")
    if (any(key not in payload for key in required)
            or any(not isinstance(payload[key], bool) for key in required[:5])
            or not isinstance(payload["after"], dict)):
        raise UserError("el helper Perl devolvió una respuesta JSON incompleta o mal formada")
    return payload


def main():
    module = AnsibleModule(
        argument_spec=dict(
            instance=dict(type="str", required=True),
            username=dict(type="str", required=True),
            password=dict(type="str", required=True, no_log=True),
            surname=dict(type="str", required=True),
            firstname=dict(type="str"),
            library=dict(type="str", required=True),
            category=dict(type="str", required=True),
            cardnumber=dict(type="str"),
            email=dict(type="str"),
            permissions=dict(type="dict", default={}),
            timeout=dict(type="int", default=120),
            _user_helper=dict(type="path", required=True, no_log=True),
        ), supports_check_mode=True,
    )
    p = module.params
    instance = p["instance"]
    try:
        _validate(p)
        permissions = _permissions(p["permissions"])
        if os.geteuid() != 0:
            raise UserError("Ejecute con become: true para usar koha-shell con los permisos de Koha")
        conf = "/etc/koha/sites/%s/koha-conf.xml" % instance
        if not os.path.isfile(conf) or not os.access(conf, os.R_OK):
            raise UserError("No existe una configuración legible para la instancia '%s'" % instance)
        try:
            pwd.getpwnam(instance + "-koha")
        except KeyError:
            raise UserError("La instancia Koha '%s' no existe (falta su usuario de sistema)" % instance)
        helper_arg = p["_user_helper"]
        helper = os.path.realpath(helper_arg)
        if (os.path.islink(helper_arg) or helper != helper_arg or not os.path.isfile(helper)
                or not HELPER_RE.fullmatch(helper) or not os.stat(helper).st_mode & stat.S_IRUSR):
            raise UserError("No se encontró el helper temporal user.pl de la colección")
        koha_shell = module.get_bin_path("koha-shell", required=False)
        if not koha_shell:
            raise UserError("koha-shell no está disponible en el host administrado")
        desired = {key: p[key] for key in ("username", "password", "surname", "firstname", "library", "category",
                                           "cardnumber", "email")}
        desired["permissions"] = permissions
        # Staging path is generated by the collection action plugin and restricted above.
        command = [koha_shell, instance, "-c", "perl %s" % helper]
        request = {"protocol": PROTOCOL, "operation": "configure", "desired": desired,
                   "apply": not module.check_mode}
        with (contextlib.nullcontext() if module.check_mode else _instance_lock(instance)):
            payload = _read_protocol(command, request, p["timeout"])
        result = dict(instance=instance, changed=payload["changed"], borrowernumber=payload.get("borrowernumber"),
                      created=payload["created"], updated=payload["updated"],
                      permissions_changed=payload["permissions_changed"], password_changed=payload["password_changed"],
                      before=payload["before"], after=payload["after"])
        if module._diff:
            result["diff"] = {"before": payload["before"] or {}, "after": payload["after"]}
        result["msg"] = ("Cambios de usuario proyectados." if module.check_mode and result["changed"]
                         else "El usuario ya está como se declaró." if not result["changed"]
                         else "Usuario configurado.")
        module.exit_json(**result)
    except (UserError, OSError, ValueError, UnicodeError) as exc:
        module.fail_json(msg=str(exc), instance=instance, changed=getattr(exc, "changed", False))


if __name__ == "__main__":
    main()
