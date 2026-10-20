# SPDX-License-Identifier: MIT-0
#!/usr/bin/python
"""Initialize a Koha database and complete its first-use onboarding."""

DOCUMENTATION = r'''
---
module: initialize
short_description: Inicializa la base de datos y el onboarding inicial de Koha
description:
  - Usa C4::Installer y las clases de dominio de Koha mediante un helper Perl independiente.
  - Solo crea objetos ausentes; los conflictos con objetos existentes se informan y no se reconcilian de manera implícita.
  - No migra una base existente ni elimina información.
version_added: "1.2.0"
author: Jonas MZ
requirements:
  - Koha instalado desde paquetes Debian o Ubuntu.
  - koha-shell y las APIs Perl de Koha disponibles en el host administrado.
  - Privilegios para acceder a la instancia seleccionada y crear el esquema cuando haga falta.
options:
  instance:
    description: Nombre de la instancia Koha; debe corresponder a /etc/koha/sites/INSTANCE/koha-conf.xml.
    type: str
    required: true
  state:
    description: present ejecuta la inicialización; inspect consulta el estado sin modificarlo.
    type: str
    choices: [present, inspect]
    default: present
  language:
    description: Código de idioma disponible en el catálogo de Koha usado para seleccionar los datos iniciales.
    type: str
    required: true
  marcflavor:
    description: Variante MARC instalada por el paquete y reconocida por C4::Installer; coincide con jmz.koha.instance.
    type: str
    choices: [MARC21, UNIMARC]
    required: true
    aliases: [marc_flavour]
  sample_data:
    description: Identificadores opcionales C(section/archivo.sql) del catálogo de Koha; los datos demostrativos no se cargan por defecto.
    type: list
    elements: str
    default: []
  library:
    description: Biblioteca inicial. Una entidad existente debe coincidir con los atributos declarados.
    type: dict
    required: true
    options:
      code: {description: Código de biblioteca Koha., type: str, required: true}
      name: {description: Nombre de biblioteca., type: str, required: true}
  patron_categories:
    description: Categorías requeridas. La categoría del administrador debe ser de tipo S.
    type: list
    elements: dict
    required: true
    options:
      code: {description: Código de categoría., type: str, required: true}
      description: {description: Descripción., type: str, required: true}
      type: {description: Tipo Koha., type: str, choices: [A, C, I, S, X], required: true}
      enrolment_period: {description: Vigencia en años exigida por el esquema., type: int, required: true}
      default_privacy: {description: Preferencia de privacidad predeterminada., type: str, choices: [default, never, forever, holds], required: true}
  administrator:
    description: Cuenta inicial. Si ya existe, su contraseña no se cambia; un conflicto de identidad o permisos falla.
    type: dict
    required: true
    no_log: true
    options:
      username: {description: Identificador de acceso., type: str, required: true}
      firstname: {description: Nombre., type: str, required: true}
      surname: {description: Apellido., type: str, required: true}
      cardnumber: {description: Número de tarjeta., type: str, required: true}
      library: {description: Código de biblioteca existente., type: str, required: true}
      category: {description: Código de una categoría de personal tipo S., type: str, required: true}
      email: {description: Correo opcional del administrador; si la cuenta existente no tiene correo se completa, y si ya tiene otro valor se reporta conflicto., type: str}
      password: {description: Contraseña inicial, validada y almacenada por Koha. No se rota en cuentas existentes., type: str, required: true, no_log: true}
  item_types:
    description: Uno o más tipos de material iniciales; los existentes deben coincidir en descripción.
    type: list
    elements: dict
    required: true
    options:
      code: {description: Código del tipo de material., type: str, required: true}
      description: {description: Descripción., type: str, required: true}
  circulation_rules:
    description: Reglas explícitas para biblioteca, categoría y tipo de material. No se inventa una política predeterminada.
    type: list
    elements: dict
    required: true
    options:
      library: {description: Código de biblioteca o * para el ámbito global., type: str, required: true}
      category: {description: Código de categoría o * para el ámbito global., type: str, required: true}
      item_type: {description: Código de tipo de material o * para el ámbito global., type: str, required: true}
      rules: {description: Mapa no vacío de nombres y valores admitidos por Koha::CirculationRules., type: dict, required: true}
  timeout:
    description: Tiempo máximo en segundos para cada llamada al helper Koha.
    type: int
    default: 1800
'''

EXAMPLES = r'''
- name: Inicializar Koha y completar onboarding
  jmz.koha.initialize:
    instance: biblioteca
    language: es-ES
    marcflavor: MARC21
    library:
      code: CENTRAL
      name: Biblioteca Central
    patron_categories:
      - code: STAFF
        description: Personal bibliotecario
        type: S
        enrolment_period: 1
        default_privacy: default
      - code: ADULT
        description: Usuarios adultos
        type: A
        enrolment_period: 1
        default_privacy: default
    administrator:
      username: admin
      firstname: Administrador
      surname: Koha
      cardnumber: ADMIN001
      library: CENTRAL
      category: STAFF
      email: "{{ vault_koha_admin_email }}"
      password: "{{ vault_koha_admin_password }}"
    item_types:
      - code: BOOK
        description: Libros
    circulation_rules:
      - library: CENTRAL
        category: ADULT
        item_type: BOOK
        rules:
          issuelength: 14
          lengthunit: days
          maxissueqty: 5
          renewalsallowed: 2
  become: true
  no_log: true

- name: Inspeccionar sin cambios
  jmz.koha.initialize:
    instance: biblioteca
    state: inspect
    language: es-ES
    marcflavor: MARC21
  become: true

- name: Ejecutar en modo de comprobación
  jmz.koha.initialize:
    instance: biblioteca
    language: es-ES
    marcflavor: UNIMARC
    # Los datos y entidades requeridos se declaran igual que en el ejemplo completo.
  check_mode: true
  become: true
  no_log: true
'''

RETURN = r'''
instance:
  description: Instancia inspeccionada o inicializada.
  returned: always
  type: str
previous_state:
  description: Estado observado antes de ejecutar el plan o la inicialización.
  returned: always
  type: str
  sample: uninitialized
current_state:
  description: Estado observado al finalizar; no se simula un estado exitoso ante errores.
  returned: always
  type: str
  sample: initialized
actions:
  description: Operaciones verificadas que se realizaron.
  returned: always
  type: list
validation:
  description: Comprobaciones posteriores de esquema y onboarding.
  returned: en inicialización exitosa
  type: dict
warnings:
  description: Avisos de compatibilidad devueltos por las APIs de Koha.
  returned: en inicialización exitosa o parcial
  type: list
state_info:
  description: Indicadores de esquema y entidades observados por Koha.
  returned: siempre en inspect o después de inicialización exitosa
  type: dict
koha_version:
  description: Versión del software informada por Koha.
  returned: en inspect
  type: str
capabilities:
  description: Presencia de los métodos de instalación consultados.
  returned: en inspect
  type: dict
planned:
  description: Indica que la respuesta es un plan de check mode.
  returned: en check mode
  type: bool
partial:
  description: Indica que check mode solo pudo planificar el estado global.
  returned: en check mode
  type: bool
msg:
  description: Resumen del resultado.
  returned: always
  type: str
'''

import json
import os
import pwd
import re
import stat
import fcntl
import subprocess
import contextlib
import signal
import xml.etree.ElementTree as ET

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import (
    choice_normalizer, ensure_mariadb_timezone, ModuleInputError,
)


INSTANCE_RE = re.compile(r"^[a-z][a-z0-9-]{0,10}$")
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,10}$")
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.(?:sql|yml)$")
RULE_NAME_ALIASES = {"maxissuesqty": "maxissueqty"}
PROTOCOL = 1
STATES = {"uninitialized", "schema_created", "data_incomplete", "onboarding_required", "initialized", "inconsistent", "upgrade_required"}


class InitializeError(Exception):
    """A safe initialization or protocol failure."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or {}


def _validate_params(module):
    p = module.params
    if "marcflavor" not in p:
        p["marcflavor"] = p.get("marc_flavour")
    instance = p["instance"]
    if not INSTANCE_RE.fullmatch(instance):
        raise InitializeError("instance debe ser un identificador Koha válido (1-11 caracteres, minúsculas, números o guiones)")
    if p["state"] == "inspect":
        if p.get("administrator") or p.get("library") or p.get("patron_categories") or p.get("item_types") or p.get("circulation_rules"):
            raise InitializeError("state=inspect no acepta parámetros de onboarding")
        return
    for required in ("language", "marcflavor", "library", "patron_categories", "administrator", "item_types", "circulation_rules"):
        if p.get(required) is None:
            raise InitializeError("%s es obligatorio cuando state=present" % required)
    if not LANGUAGE_RE.fullmatch(p["language"]):
        raise InitializeError("language debe ser un identificador BCP 47 simple, por ejemplo en o es-ES")
    lib = p["library"]
    if not CODE_RE.fullmatch(lib["code"]):
        raise InitializeError("library.code debe contener entre 1 y 10 caracteres alfanuméricos, guion o guion bajo")
    cats = {item["code"]: item for item in p["patron_categories"]}
    if not cats or any(not CODE_RE.fullmatch(code) for code in cats):
        raise InitializeError("patron_categories requiere códigos válidos y al menos una categoría")
    if not any(category["type"] in ("A", "C", "I") for category in cats.values()):
        raise InitializeError("patron_categories debe incluir una categoría no staff para usuarios del OPAC")
    for category in cats.values():
        if category["enrolment_period"] <= 0:
            raise InitializeError("enrolment_period debe ser positivo")
    admin = p["administrator"]
    if admin["library"] != lib["code"]:
        raise InitializeError("administrator.library debe coincidir con library.code")
    if admin["category"] not in cats or cats[admin["category"]]["type"] != "S":
        raise InitializeError("administrator.category debe referenciar una categoría declarada de tipo S")
    types = {item["code"] for item in p["item_types"]}
    if not types or any(not CODE_RE.fullmatch(code) for code in types):
        raise InitializeError("item_types requiere códigos válidos y al menos un tipo")
    if not p["circulation_rules"]:
        raise InitializeError("Debe declararse al menos una regla explícita de circulación")
    for rule in p["circulation_rules"]:
        if rule["library"] not in ("*", lib["code"]):
            raise InitializeError("circulation_rules referencia una biblioteca no declarada")
        if rule["category"] != "*" and rule["category"] not in cats:
            raise InitializeError("circulation_rules referencia una categoría no declarada")
        if rule["item_type"] != "*" and rule["item_type"] not in types:
            raise InitializeError("circulation_rules referencia un tipo de material no declarado")
        if not rule["rules"]:
            raise InitializeError("cada entrada de circulation_rules.rules debe contener al menos una regla")
        normalized_rules = {}
        for name, value in rule["rules"].items():
            if not isinstance(name, str):
                raise InitializeError("los nombres de circulation_rules.rules deben ser texto")
            # Koha's rule identifiers are lowercase; accept the common
            # camelCase spelling used in role variables, then send Koha's API
            # canonical names. One historical typo is kept as an alias.
            canonical = RULE_NAME_ALIASES.get(name.lower(), name.lower())
            if not re.fullmatch(r"[a-z][a-z0-9_]*", canonical):
                raise InitializeError("nombre de regla de circulación inválido: %s" % name)
            if canonical in normalized_rules:
                raise InitializeError("circulation_rules contiene nombres duplicados para la regla %s" % canonical)
            normalized_rules[canonical] = value
        rule["rules"] = normalized_rules
    for identifier in p["sample_data"]:
        if not IDENTIFIER_RE.fullmatch(identifier) or ".." in identifier.split("/"):
            raise InitializeError("sample_data solo acepta identificadores del catálogo Koha en formato section/file.sql")


def _read_protocol(module, command, request, timeout):
    process = None
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            start_new_session=True,
        )
        stdout_bytes, stderr_bytes = process.communicate(
            input=json.dumps(request, ensure_ascii=False).encode("utf-8"), timeout=timeout
        )
    except subprocess.TimeoutExpired:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
        raise InitializeError("koha-shell excedió el límite de %s segundos" % timeout)
    rc = process.returncode
    stdout = stdout_bytes.decode("utf-8", "replace")
    stderr = stderr_bytes.decode("utf-8", "replace")
    try:
        payload = json.loads(stdout)
    except (TypeError, ValueError):
        raise InitializeError("El helper Perl no devolvió JSON válido (rc=%s); se omitió la salida cruda para proteger credenciales" % rc)
    if not isinstance(payload, dict) or payload.get("protocol") != PROTOCOL:
        raise InitializeError("Versión o estructura de protocolo Python/Perl incompatible")
    if rc != 0 or payload.get("ok") is not True:
        error = payload.get("error") or {}
        raise InitializeError("%s: %s" % (error.get("type", "koha_error"), error.get("message", "falló la llamada a Koha")),
                              error.get("details"))
    return payload


def _ensure_instance_timezone(module, conf):
    """Ensure the instance's named timezone is available in its MariaDB."""
    try:
        root = ET.parse(conf).getroot()
    except (ET.ParseError, OSError) as exc:
        raise InitializeError("No se pudo leer koha-conf.xml para comprobar su zona horaria") from exc
    timezone = (root.findtext("timezone") or "").strip()
    if not timezone:
        return False
    dbhost = (root.findtext("./database/hostname") or "localhost").strip()
    try:
        return ensure_mariadb_timezone(module, timezone, dbhost)
    except ModuleInputError as exc:
        raise InitializeError(str(exc)) from exc


def main():
    module = AnsibleModule(
        argument_spec=dict(
            instance=dict(type="str", required=True),
            state=dict(type=choice_normalizer(["present", "inspect"]), choices=["present", "inspect"], default="present"),
            language=dict(type="str"),
            marcflavor=dict(type=choice_normalizer(["MARC21", "UNIMARC"]), choices=["MARC21", "UNIMARC"], aliases=["marc_flavour"]),
            sample_data=dict(type="list", elements="str", default=[]),
            library=dict(type="dict", options=dict(code=dict(type="str", required=True), name=dict(type="str", required=True))),
            patron_categories=dict(type="list", elements="dict", options=dict(
                code=dict(type="str", required=True), description=dict(type="str", required=True),
                type=dict(type=choice_normalizer(["A", "C", "I", "S", "X"]), choices=["A", "C", "I", "S", "X"], required=True),
                enrolment_period=dict(type="int", required=True),
                default_privacy=dict(type=choice_normalizer(["default", "never", "forever", "holds"]), choices=["default", "never", "forever", "holds"], required=True),
            )),
            administrator=dict(type="dict", no_log=True, options=dict(
                username=dict(type="str", required=True), firstname=dict(type="str", required=True),
                surname=dict(type="str", required=True), cardnumber=dict(type="str", required=True),
                library=dict(type="str", required=True), category=dict(type="str", required=True),
                email=dict(type="str"),
                password=dict(type="str", required=True, no_log=True),
            )),
            item_types=dict(type="list", elements="dict", options=dict(code=dict(type="str", required=True), description=dict(type="str", required=True))),
            circulation_rules=dict(type="list", elements="dict", options=dict(
                library=dict(type="str", required=True), category=dict(type="str", required=True),
                item_type=dict(type="str", required=True), rules=dict(type="dict", required=True),
            )),
            timeout=dict(type="int", default=1800),
            _initialize_helper=dict(type="path", required=True, no_log=True),
        ),
        supports_check_mode=True,
    )
    p = module.params
    instance = p["instance"]
    timezone_changed = False
    try:
        _validate_params(module)
        conf = "/etc/koha/sites/%s/koha-conf.xml" % instance
        if not os.path.isfile(conf) or not os.access(conf, os.R_OK):
            raise InitializeError("No existe una configuración legible de Koha para la instancia %s" % instance)
        if os.geteuid() != 0:
            raise InitializeError("Ejecute el módulo con become: true para usar koha-shell con privilegios adecuados")
        try:
            pwd.getpwnam(instance + "-koha")
        except KeyError:
            raise InitializeError("No existe el usuario de sistema %s-koha" % instance)
        koha_shell = module.get_bin_path("koha-shell", required=False)
        if not koha_shell:
            raise InitializeError("koha-shell no está disponible en el host administrado")
        helper = os.path.realpath(p["_initialize_helper"])
        if os.path.basename(helper) != "initialize.pl" or os.path.islink(p["_initialize_helper"]) or not os.path.isfile(helper):
            raise InitializeError("No se encontró el helper Perl temporal de la colección")
        if not (os.stat(helper).st_mode & stat.S_IRUSR):
            raise InitializeError("El helper Perl no es legible")
        # koha-shell wraps its -c value in single quotes before passing it to
        # the instance shell, so a shell-quoted path would break that wrapper.
        # The action plugin stages this file under an absolute, whitespace-free
        # Ansible temp path; reject anything outside that narrow safe alphabet.
        if not re.fullmatch(r"/[A-Za-z0-9._/-]+", helper):
            raise InitializeError("La ruta del helper contiene caracteres de shell no admitidos")
        shell_command = "perl %s" % helper
        command = [koha_shell, instance, "-c", shell_command]

        # flock is released automatically on process exit, including abrupt failure.
        lock_context = contextlib.nullcontext()
        if p["state"] == "present" and not module.check_mode:
            lock_path = "/run/lock/koha-initialize-%s.lock" % instance
            if not os.path.isdir("/run/lock") or not os.access("/run/lock", os.W_OK):
                lock_path = "/tmp/koha-initialize-%s.lock" % instance
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
            lock_context = os.fdopen(lock_fd, "r+")
        with lock_context as lock:
            if lock is not None:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise InitializeError("Ya hay otra inicialización activa para la instancia %s" % instance)
            # Koha connects to the database during state inspection, so repair
            # MariaDB's timezone tables before invoking its Perl APIs.
            if p["state"] == "present" and not module.check_mode:
                timezone_changed = _ensure_instance_timezone(module, conf)
            probe = _read_protocol(module, command, {"protocol": PROTOCOL, "operation": "inspect"}, p["timeout"])
            previous = probe.get("state")
            if previous not in STATES:
                raise InitializeError("El helper devolvió un estado Koha desconocido")
            if p["state"] == "inspect":
                module.exit_json(changed=False, instance=instance, previous_state=previous,
                                 current_state=previous, state_info=probe.get("state_info"),
                                 koha_version=probe.get("koha_version"), capabilities=probe.get("capabilities"),
                                 msg="Estado de Koha inspeccionado sin modificaciones.")
            if previous in ("data_incomplete", "inconsistent", "upgrade_required"):
                raise InitializeError("La instancia está en estado %s; no se reintenta ni migra automáticamente" % previous)
            request = {k: p[k] for k in ("language", "sample_data", "library", "patron_categories", "administrator", "item_types", "circulation_rules")}
            request["marc_flavour"] = p["marcflavor"]
            request.update(protocol=PROTOCOL, operation="initialize")
            if module.check_mode:
                planned = previous != "initialized"
                module.exit_json(changed=planned, instance=instance, previous_state=previous,
                                 current_state=previous, planned=True,
                                 actions=( ["schema_and_install_data"] if previous in ("uninitialized", "schema_created") else [] ) + ["onboarding"],
                                 partial=True,
                                 msg="Modo de comprobación: solo se inspeccionó el estado general; los conflictos de entidades y reglas requieren ejecución de APIs de Koha.")
            result = _read_protocol(module, command, request, p["timeout"])
            current = result.get("current_state")
            if current != "initialized":
                raise InitializeError("La inicialización terminó sin alcanzar el estado initialized (observado: %s)" % current)
            actions = result.get("actions", [])
            if timezone_changed:
                actions = ["cargar tablas de zonas horarias MariaDB"] + actions
            module.exit_json(changed=bool(result.get("changed")) or timezone_changed, instance=instance,
                             previous_state=result.get("previous_state", previous), current_state=current,
                             actions=actions, validation=result.get("validation", {}),
                             state_info=result.get("state_info"), warnings=result.get("warnings", []),
                             diff={"before": previous, "after": current} if module._diff else None,
                             msg="La inicialización de Koha y el onboarding finalizaron correctamente.")
    except (InitializeError, OSError, ValueError) as exc:
        details = getattr(exc, "details", {})
        module.fail_json(msg=str(exc), instance=instance,
                         current_state=details.get("current_state", locals().get("current")),
                         previous_state=details.get("previous_state", locals().get("previous")),
                         state_info=details.get("state_info"),
                         changed=details.get("changed", timezone_changed), partial=details.get("partial", timezone_changed),
                         actions=details.get("actions", locals().get("actions", [])),
                         warnings=details.get("warnings", []), phase=details.get("phase"))


if __name__ == "__main__":
    main()
