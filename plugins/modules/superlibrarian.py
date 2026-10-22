#!/usr/bin/python
# SPDX-License-Identifier: MIT-0
"""Restore the Koha superlibrarian account and report any other superlibrarian."""

DOCUMENTATION = r'''
---
module: superlibrarian
short_description: Restablece la cuenta superlibrarian de Koha y avisa de otros superlibrarians
description:
  - Garantiza que la cuenta C(username) exista, sea superlibrarian, tenga la identidad y la contraseña declaradas, no esté vencida, bloqueada ni restringida.
  - Si la cuenta fue borrada, la crea de nuevo.
  - Compara contra el estado real en cada ejecución, así que sirve como control de cumplimiento tras cambios hechos por otros usuarios con permisos de gestión de personal.
  - Avisa (C(warnings) y C(unexpected_superlibrarians)) de cualquier otro usuario con privilegio superlibrarian que no esté en C(allowed). Nunca lo modifica.
  - No concede superlibrarian a ninguna otra cuenta ni administra los permisos de otros usuarios; para eso está C(user).
  - Restablecer la cuenta no deshace lo que se haya hecho con ella (usuarios, preferencias del sistema, etc.).
  - Requiere que C(initialize) haya completado la base de datos.
version_added: "1.4.0"
author: Jonas MZ
requirements:
  - Koha empaquetado para Debian/Ubuntu y koha-shell.
options:
  instance:
    description: Instancia Koha existente.
    type: str
    required: true
  username:
    description: Identificador de acceso (C(userid)) de la cuenta superlibrarian.
    type: str
    required: true
  password:
    description: Contraseña; debe cumplir la política de la categoría. Se restablece solo si difiere de la guardada.
    type: str
    required: true
    no_log: true
  surname:
    description: Apellido.
    type: str
    required: true
  firstname:
    description: Nombre. Si se omite no se modifica el guardado.
    type: str
  library:
    description: Código de una biblioteca existente.
    type: str
    required: true
  category:
    description: Código de una categoría de personal (tipo S) existente.
    type: str
    required: true
  cardnumber:
    description: Número de tarjeta. Si se omite no se modifica el guardado.
    type: str
  email:
    description: Correo electrónico. Si se omite no se modifica el guardado.
    type: str
  allowed:
    description:
      - Otros C(userid) que pueden ser superlibrarian sin generar aviso ni bloqueo.
      - Con C(unexpected=lock), los de esta lista que un bloqueo anterior dejó bloqueados se desbloquean.
    type: list
    elements: str
    default: []
  unexpected:
    description:
      - Qué hacer con los demás superlibrarians, los que no son C(username) ni están en C(allowed).
      - C(warn) solo informa. C(lock) además los bloquea administrativamente, sin quitarles el privilegio, vencerlos ni borrar nada; es reversible.
      - Con C(lock), solo se desbloquean los superlibrarians declarados en C(allowed); ningún otro bloqueo se deshace.
    type: str
    choices: [warn, lock]
    default: warn
  timeout:
    description: Timeout, en segundos, de la llamada a koha-shell.
    type: int
    default: 120
'''

EXAMPLES = r'''
- name: Mantener la cuenta administradora
  jmz.koha.superlibrarian:
    instance: biblioteca
    username: admin
    password: "{{ vault_admin_password }}"
    surname: Koha
    firstname: Ada
    cardnumber: ADMIN01
    email: admin@example.org
    library: CENTRAL
    category: STAFF
    allowed: [soporte]
    unexpected: lock
  become: true
  no_log: true
'''

RETURN = r'''
instance: {description: Instancia Koha., returned: always, type: str}
borrowernumber: {description: Identificador del usuario en Koha; nulo en check mode si se crearía., returned: always, type: int}
created: {description: Si la cuenta no existía y se creó., returned: always, type: bool}
updated: {description: Si se corrigió la identidad., returned: always, type: bool}
superlibrarian_restored: {description: Si la cuenta había perdido el privilegio y se restableció., returned: always, type: bool}
password_changed: {description: Si cambió la contraseña de una cuenta existente., returned: always, type: bool}
expiry_renewed: {description: Si la cuenta estaba vencida y se renovó., returned: always, type: bool}
unlocked: {description: Si la cuenta estaba bloqueada y se desbloqueó., returned: always, type: bool}
restrictions_removed: {description: Si se quitaron restricciones de la cuenta., returned: always, type: bool}
unexpected_superlibrarians: {description: Otros usuarios con privilegio superlibrarian que no están en C(allowed)., returned: always, type: list, elements: str}
locked_superlibrarians: {description: Superlibrarians no previstos que esta ejecución bloqueó (con C(unexpected=lock))., returned: always, type: list, elements: str}
restored_superlibrarians: {description: Superlibrarians declarados en C(allowed) que esta ejecución desbloqueó (con C(unexpected=lock))., returned: always, type: list, elements: str}
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
from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import NAME_RE, ModuleInputError, choice_normalizer
from ansible_collections.jmz.koha.plugins.module_utils.koha_lock import exclusive_lock


PROTOCOL = 1
HELPER_RE = re.compile(r"^/tmp/ansible-koha-superlibrarian-[0-9a-f]{32}/superlibrarian\.pl$")
UNEXPECTED = ["warn", "lock"]
OUTPUT_LIMIT = 6000


class SuperlibrarianError(Exception):
    def __init__(self, message, changed=False):
        super().__init__(message)
        self.changed = changed


def _plain_text(value, name, limit=80):
    if not value.strip() or len(value) > limit or any(c in value for c in "\r\n\x00"):
        raise SuperlibrarianError("%s debe ser un texto de hasta %d caracteres, sin saltos de línea ni NUL" % (name, limit))


def _validate(params):
    if not NAME_RE.fullmatch(params["instance"]):
        raise SuperlibrarianError("instance debe tener 1-11 caracteres: minúsculas, números o guiones; debe comenzar por letra")
    _plain_text(params["username"], "username", 75)
    _plain_text(params["surname"], "surname")
    for key in ("firstname", "cardnumber", "email"):
        if params[key] is not None:
            _plain_text(params[key], key, 255)
    for key in ("library", "category"):
        _plain_text(params[key], key, 10)
    if not params["password"] or any(c in params["password"] for c in "\r\n\x00"):
        raise SuperlibrarianError("password no puede estar vacía ni contener saltos de línea o NUL")
    for userid in params["allowed"]:
        _plain_text(userid, "allowed", 75)
    if params["timeout"] <= 0:
        raise SuperlibrarianError("timeout debe ser positivo")


@contextlib.contextmanager
def _instance_lock(instance):
    """Serialize runs per instance so two runs cannot both create the account."""
    try:
        with exclusive_lock("superlibrarian", instance, "otra ejecución está configurando el superlibrarian en %s; reintente cuando termine" % instance,
                            wait=30):
            yield
    except ModuleInputError as exc:
        raise SuperlibrarianError(str(exc))


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
        raise SuperlibrarianError("koha-shell excedió el límite de %s segundos; la operación es transaccional, reintente" % timeout)
    except OSError as exc:
        raise SuperlibrarianError("no se pudo ejecutar koha-shell: %s" % exc)
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, TypeError, ValueError):
        raise SuperlibrarianError("el helper Perl no devolvió JSON válido (rc=%s): %s"
                        % (process.returncode, stderr.decode("utf-8", "replace")[:OUTPUT_LIMIT]))
    if not isinstance(payload, dict) or payload.get("protocol") != PROTOCOL or not isinstance(payload.get("ok"), bool):
        raise SuperlibrarianError("el helper Perl devolvió un protocolo incompleto o incompatible")
    if process.returncode != 0 or not payload["ok"]:
        # "committed" means the transaction finished before a later check failed: Koha was changed.
        raise SuperlibrarianError((payload.get("error") or {}).get("message", "falló la operación de Koha"),
                        changed=payload.get("committed") is True)
    required = ("changed", "created", "updated", "superlibrarian_restored", "password_changed", "expiry_renewed", "unlocked",
                "restrictions_removed", "unexpected_superlibrarians", "locked_superlibrarians", "restored_superlibrarians",
                "before", "after")
    if (any(key not in payload for key in required)
            or any(not isinstance(payload[key], bool) for key in required[:8])
            or any(not isinstance(payload[key], list) for key in required[8:11])
            or not isinstance(payload["after"], dict)):
        raise SuperlibrarianError("el helper Perl devolvió una respuesta JSON incompleta o mal formada")
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
            allowed=dict(type="list", elements="str", default=[]),
            unexpected=dict(type=choice_normalizer(UNEXPECTED), choices=UNEXPECTED, default="warn"),
            timeout=dict(type="int", default=120),
            _superlibrarian_helper=dict(type="path", required=True, no_log=True),
        ), supports_check_mode=True,
    )
    p = module.params
    instance = p["instance"]
    try:
        _validate(p)
        if os.geteuid() != 0:
            raise SuperlibrarianError("Ejecute con become: true para usar koha-shell con los permisos de Koha")
        conf = "/etc/koha/sites/%s/koha-conf.xml" % instance
        if not os.path.isfile(conf) or not os.access(conf, os.R_OK):
            raise SuperlibrarianError("No existe una configuración legible para la instancia '%s'" % instance)
        try:
            pwd.getpwnam(instance + "-koha")
        except KeyError:
            raise SuperlibrarianError("La instancia Koha '%s' no existe (falta su usuario de sistema)" % instance)
        helper_arg = p["_superlibrarian_helper"]
        helper = os.path.realpath(helper_arg)
        if (os.path.islink(helper_arg) or helper != helper_arg or not os.path.isfile(helper)
                or not HELPER_RE.fullmatch(helper) or not os.stat(helper).st_mode & stat.S_IRUSR):
            raise SuperlibrarianError("No se encontró el helper temporal superlibrarian.pl de la colección")
        koha_shell = module.get_bin_path("koha-shell", required=False)
        if not koha_shell:
            raise SuperlibrarianError("koha-shell no está disponible en el host administrado")
        desired = {key: p[key] for key in ("username", "password", "surname", "firstname", "library", "category",
                                           "cardnumber", "email")}
        desired["allowed"] = p["allowed"]
        desired["unexpected"] = p["unexpected"]
        # Staging path is generated by the collection action plugin and restricted above.
        command = [koha_shell, instance, "-c", "perl %s" % helper]
        request = {"protocol": PROTOCOL, "operation": "configure", "desired": desired,
                   "apply": not module.check_mode}
        with (contextlib.nullcontext() if module.check_mode else _instance_lock(instance)):
            payload = _read_protocol(command, request, p["timeout"])
        unexpected = payload["unexpected_superlibrarians"]
        result = dict(instance=instance, changed=payload["changed"], borrowernumber=payload.get("borrowernumber"),
                      created=payload["created"], updated=payload["updated"],
                      superlibrarian_restored=payload["superlibrarian_restored"],
                      password_changed=payload["password_changed"], expiry_renewed=payload["expiry_renewed"],
                      unlocked=payload["unlocked"], restrictions_removed=payload["restrictions_removed"],
                      unexpected_superlibrarians=unexpected, locked_superlibrarians=payload["locked_superlibrarians"],
                      restored_superlibrarians=payload["restored_superlibrarians"], before=payload["before"], after=payload["after"])
        locked = payload["locked_superlibrarians"]
        if locked:
            module.warn("Se %s los superlibrarians no previstos de %s: %s (conservan el privilegio; use allowed para aceptarlos)"
                        % ("bloquearían" if module.check_mode else "bloquearon", instance, ", ".join(locked)))
        elif unexpected:
            module.warn("Hay otros superlibrarians no previstos en %s: %s (no se modificaron; use allowed para aceptarlos)"
                        % (instance, ", ".join(unexpected)))
        if module._diff:
            result["diff"] = {"before": payload["before"] or {}, "after": payload["after"]}
        result["msg"] = ("Cambios de la cuenta superlibrarian proyectados." if module.check_mode and result["changed"]
                         else "La cuenta superlibrarian ya está como se declaró." if not result["changed"]
                         else "Cuenta superlibrarian restablecida.")
        module.exit_json(**result)
    except (SuperlibrarianError, OSError, ValueError, UnicodeError) as exc:
        module.fail_json(msg=str(exc), instance=instance, changed=getattr(exc, "changed", False))


if __name__ == "__main__":
    main()
