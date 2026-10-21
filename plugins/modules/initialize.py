# SPDX-License-Identifier: MIT-0
#!/usr/bin/python
"""Initialize a Koha database and complete its first-use onboarding."""

DOCUMENTATION = r'''
---
module: initialize
short_description: Inicializa la base de datos y el onboarding inicial de Koha
description:
  - Usa C4::Installer y las clases de dominio de Koha mediante un helper Perl independiente.
  - No carga las tablas de zonas horarias de MariaDB; si la instancia usa una zona con nombre, ejecute antes M(jmz.koha.mariadb_timezone).
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
    description: present ejecuta la inicialización; inspect consulta el estado sin modificarlo y no acepta parámetros de onboarding.
    type: str
    choices: [present, inspect]
    default: present
  language:
    description:
      - Código de idioma disponible en el catálogo de Koha usado para seleccionar los datos iniciales. Obligatorio con I(state=present).
      - Solo se usa al instalar. En una instancia ya instalada no se compara con los idiomas habilitados (eso lo administra M(jmz.koha.localization)); si no está habilitado, se emite una advertencia.
    type: str
  marcflavor:
    description:
      - Variante MARC instalada por el paquete y reconocida por C4::Installer; usa los mismos valores que M(jmz.koha.instance).
      - Acepta mayúsculas y minúsculas; Koha la almacena en mayúsculas.
      - Obligatoria con I(state=present).
    type: str
    choices: [marc21, unimarc]
  sample_data:
    description: Identificadores opcionales C(section/archivo.sql) del catálogo de Koha; los datos demostrativos no se cargan por defecto.
    type: list
    elements: str
    default: []
  library:
    description: Biblioteca inicial. Una entidad existente debe coincidir con los atributos declarados. Obligatoria con I(state=present).
    type: dict
    options:
      code: {description: Código de biblioteca Koha., type: str, required: true}
      name: {description: Nombre de biblioteca., type: str, required: true}
  patron_categories:
    description: Categorías requeridas, sin códigos repetidos. La categoría del administrador debe ser de tipo S. Obligatoria con I(state=present).
    type: list
    elements: dict
    options:
      code: {description: Código de categoría., type: str, required: true}
      description: {description: Descripción., type: str, required: true}
      type: {description: Tipo Koha., type: str, choices: [A, C, I, S, X], required: true}
      enrolment_period: {description: Vigencia en años exigida por el esquema., type: int, required: true}
      default_privacy: {description: Preferencia de privacidad predeterminada., type: str, choices: [default, never, forever, holds], required: true}
  administrator:
    description: Cuenta inicial. Si ya existe, su contraseña no se cambia; un conflicto de identidad o permisos falla. Obligatoria con I(state=present).
    type: dict
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
    description: Uno o más tipos de material iniciales, sin códigos repetidos; los existentes deben coincidir en descripción. Obligatorio con I(state=present).
    type: list
    elements: dict
    options:
      code: {description: Código del tipo de material., type: str, required: true}
      description: {description: Descripción., type: str, required: true}
  circulation_rules:
    description:
      - Reglas explícitas para biblioteca, categoría y tipo de material, sin ámbitos repetidos. No se inventa una política predeterminada.
      - Obligatorias con I(state=present).
    type: list
    elements: dict
    options:
      library: {description: Código de biblioteca o * para el ámbito global., type: str, required: true}
      category: {description: Código de categoría o * para el ámbito global., type: str, required: true}
      item_type: {description: Código de tipo de material o * para el ámbito global., type: str, required: true}
      rules: {description: Mapa no vacío de nombres y valores escalares admitidos por Koha::CirculationRules; los nombres no distinguen mayúsculas., type: dict, required: true}
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
    marcflavor: marc21
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
    marcflavor: unimarc
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

import contextlib
import json
import os
import pwd
import re
import stat
import subprocess
import signal

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import NAME_RE, ModuleInputError, choice_normalizer
from ansible_collections.jmz.koha.plugins.module_utils.koha_lock import exclusive_lock


HELPER_RE = re.compile(r"^/tmp/ansible-koha-initialize-[0-9a-f]{32}/initialize\.pl$")
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,10}$")
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.(?:sql|yml)$")
RULE_VALUE_TYPES = (str, int, float, bool)
TIMEZONE_HINT = " Las tablas de zonas horarias de MariaDB no están cargadas; ejecute jmz.koha.mariadb_timezone antes de inicializar."
STDERR_LIMIT = 600
PROTOCOL = 1
STATES = {"uninitialized", "schema_created", "data_incomplete", "onboarding_required", "initialized", "inconsistent", "upgrade_required"}


class InitializeError(Exception):
    """A safe initialization or protocol failure."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or {}


def _unique(items, key, label):
    codes = [item[key] for item in items]
    duplicated = sorted({code for code in codes if codes.count(code) > 1})
    if duplicated:
        raise InitializeError("%s contiene códigos repetidos: %s" % (label, ", ".join(duplicated)))


def _normalize_rules(rules):
    """Return Koha's lowercase rule names mapped to scalar values."""
    normalized = {}
    for name, value in rules.items():
        if not isinstance(name, str):
            raise InitializeError("los nombres de circulation_rules.rules deben ser texto")
        # Koha's rule identifiers are lowercase; accept the common camelCase spelling used in role variables.
        canonical = name.lower()
        if not re.fullmatch(r"[a-z][a-z0-9_]*", canonical):
            raise InitializeError("nombre de regla de circulación inválido: %s" % name)
        if canonical in normalized:
            raise InitializeError("circulation_rules contiene nombres duplicados para la regla %s" % canonical)
        if not isinstance(value, RULE_VALUE_TYPES):
            raise InitializeError("el valor de la regla %s debe ser un texto, número o booleano" % canonical)
        normalized[canonical] = value
    return normalized


def _validate_params(module):
    p = module.params
    instance = p["instance"]
    if not NAME_RE.fullmatch(instance):
        raise InitializeError("instance debe ser un identificador Koha válido (1-11 caracteres, minúsculas, números o guiones)")
    if p["state"] == "inspect":
        onboarding = ("language", "marcflavor", "library", "patron_categories", "administrator", "item_types", "circulation_rules")
        if any(p.get(name) for name in onboarding) or p.get("sample_data"):
            raise InitializeError("state=inspect no acepta parámetros de onboarding")
        return
    # required_if only sees missing keys; an explicit null would otherwise fail deep inside the checks.
    for name in ("language", "marcflavor", "library", "patron_categories", "administrator", "item_types", "circulation_rules"):
        if p.get(name) is None:
            raise InitializeError("%s es obligatorio cuando state=present" % name)
    if not LANGUAGE_RE.fullmatch(p["language"]):
        raise InitializeError("language debe ser un identificador BCP 47 simple, por ejemplo en o es-ES")
    lib = p["library"]
    if not CODE_RE.fullmatch(lib["code"]):
        raise InitializeError("library.code debe contener entre 1 y 10 caracteres alfanuméricos, guion o guion bajo")
    if not p["patron_categories"]:
        raise InitializeError("patron_categories requiere al menos una categoría")
    _unique(p["patron_categories"], "code", "patron_categories")
    cats = {item["code"]: item for item in p["patron_categories"]}
    if any(not CODE_RE.fullmatch(code) for code in cats):
        raise InitializeError("patron_categories requiere códigos válidos")
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
    if not p["item_types"]:
        raise InitializeError("item_types requiere al menos un tipo")
    _unique(p["item_types"], "code", "item_types")
    types = {item["code"] for item in p["item_types"]}
    if any(not CODE_RE.fullmatch(code) for code in types):
        raise InitializeError("item_types requiere códigos válidos")
    if not p["circulation_rules"]:
        raise InitializeError("Debe declararse al menos una regla explícita de circulación")
    scopes = []
    for rule in p["circulation_rules"]:
        if rule["library"] not in ("*", lib["code"]):
            raise InitializeError("circulation_rules referencia una biblioteca no declarada")
        if rule["category"] != "*" and rule["category"] not in cats:
            raise InitializeError("circulation_rules referencia una categoría no declarada")
        if rule["item_type"] != "*" and rule["item_type"] not in types:
            raise InitializeError("circulation_rules referencia un tipo de material no declarado")
        if not rule["rules"]:
            raise InitializeError("cada entrada de circulation_rules.rules debe contener al menos una regla")
        scope = (rule["library"], rule["category"], rule["item_type"])
        if scope in scopes:
            raise InitializeError("circulation_rules repite el ámbito %s/%s/%s; agrupe sus reglas en una sola entrada" % scope)
        scopes.append(scope)
        rule["rules"] = _normalize_rules(rule["rules"])
    for identifier in p["sample_data"]:
        if not IDENTIFIER_RE.fullmatch(identifier) or ".." in identifier.split("/"):
            raise InitializeError("sample_data solo acepta identificadores del catálogo Koha en formato section/file.sql")


def _warn(module, warnings):
    for warning in warnings or []:
        module.warn(str(warning))


def _redact(text, secrets):
    for secret in secrets:
        if secret:
            text = text.replace(secret, "********")
    return text


def _read_protocol(module, command, request, timeout):
    process = None
    secrets = [(request.get("administrator") or {}).get("password")]
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
        raise InitializeError("koha-shell excedió el límite de %s segundos" % timeout, {"indeterminate": True})
    rc = process.returncode
    stdout = stdout_bytes.decode("utf-8", "replace")
    stderr = stderr_bytes.decode("utf-8", "replace")
    try:
        payload = json.loads(stdout)
    except (TypeError, ValueError):
        # Without a JSON answer stderr is the only clue (for example a Perl module that does not
        # compile). It is shortened, stripped of control characters and scrubbed of the password.
        tail = _redact(re.sub(r"[\x00-\x08\x0b-\x1f]", " ", stderr.strip()), secrets)[-STDERR_LIMIT:]
        message = "El helper Perl no devolvió JSON válido (rc=%s)" % rc
        if tail:
            message += ": %s" % tail
        if "time zone" in tail.lower():
            message += "." + TIMEZONE_HINT
        raise InitializeError(message, {"indeterminate": True})
    if not isinstance(payload, dict) or payload.get("protocol") != PROTOCOL:
        raise InitializeError("Versión o estructura de protocolo Python/Perl incompatible", {"indeterminate": True})
    if rc != 0 or payload.get("ok") is not True:
        error = payload.get("error") or {}
        message = "%s: %s" % (error.get("type", "koha_error"), error.get("message", "falló la llamada a Koha"))
        if "time zone" in message.lower():
            message += TIMEZONE_HINT
        raise InitializeError(message, error.get("details"))
    return payload


def _observe_after_failure(module, command, outcome):
    """Best-effort inspect after an initialize call that ended without a usable answer.

    The helper may have created the schema or loaded installer data before it
    timed out or died, so the failure must report what Koha now looks like.
    """
    try:
        state = _read_protocol(module, command, {"protocol": PROTOCOL, "operation": "inspect"}, 120).get("state")
    except (InitializeError, OSError):
        state = None
    if state in STATES:
        outcome["current_state"] = state
        if state != outcome["previous_state"]:
            outcome["changed"] = outcome["partial"] = True
        return "Estado de Koha observado tras el fallo: %s." % state
    outcome["changed"] = outcome["partial"] = True
    return "No se pudo determinar el estado de Koha tras el fallo; revise la instancia antes de reintentar."


def main():
    module = AnsibleModule(
        argument_spec=dict(
            instance=dict(type="str", required=True),
            state=dict(type=choice_normalizer(["present", "inspect"]), choices=["present", "inspect"], default="present"),
            language=dict(type="str"),
            marcflavor=dict(type=choice_normalizer(["marc21", "unimarc"]), choices=["marc21", "unimarc"]),
            sample_data=dict(type="list", elements="str", default=[]),
            library=dict(type="dict", options=dict(code=dict(type="str", required=True), name=dict(type="str", required=True))),
            patron_categories=dict(type="list", elements="dict", options=dict(
                code=dict(type="str", required=True), description=dict(type="str", required=True),
                type=dict(type=choice_normalizer(["A", "C", "I", "S", "X"]), choices=["A", "C", "I", "S", "X"], required=True),
                enrolment_period=dict(type="int", required=True),
                default_privacy=dict(type=choice_normalizer(["default", "never", "forever", "holds"]), choices=["default", "never", "forever", "holds"], required=True),
            )),
            administrator=dict(type="dict", options=dict(
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
        required_if=[("state", "present", ("language", "marcflavor", "library", "patron_categories",
                                            "administrator", "item_types", "circulation_rules"))],
        supports_check_mode=True,
    )
    p = module.params
    instance = p["instance"]
    outcome = {"previous_state": None, "current_state": None, "actions": [], "changed": False, "partial": False}
    command = None
    initializing = False
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
        helper_arg = p["_initialize_helper"]
        helper = os.path.realpath(helper_arg)
        # koha-shell wraps its -c value in single quotes, so the path must be shell-safe. The action
        # plugin stages the helper under exactly this name; accept nothing else.
        if (os.path.islink(helper_arg) or helper != helper_arg or not HELPER_RE.fullmatch(helper)
                or not os.path.isfile(helper)):
            raise InitializeError("No se encontró el helper Perl temporal de la colección")
        if not (os.stat(helper).st_mode & stat.S_IRUSR):
            raise InitializeError("El helper Perl no es legible")
        shell_command = "perl %s" % helper
        command = [koha_shell, instance, "-c", shell_command]

        # The lock is released automatically on process exit, including abrupt failure.
        lock_context = contextlib.nullcontext()
        if p["state"] == "present" and not module.check_mode:
            lock_context = exclusive_lock("initialize", instance,
                                          "Ya hay otra inicialización activa para la instancia %s" % instance)
        with lock_context:
            probe = _read_protocol(module, command, {"protocol": PROTOCOL, "operation": "inspect"}, p["timeout"])
            previous = probe.get("state")
            if previous not in STATES:
                raise InitializeError("El helper devolvió un estado Koha desconocido")
            outcome["previous_state"] = outcome["current_state"] = previous
            if p["state"] == "inspect":
                module.exit_json(changed=False, instance=instance, previous_state=previous,
                                 current_state=previous, state_info=probe.get("state_info"),
                                 koha_version=probe.get("koha_version"), capabilities=probe.get("capabilities"),
                                 msg="Estado de Koha inspeccionado sin modificaciones.")
            if previous in ("data_incomplete", "inconsistent", "upgrade_required"):
                raise InitializeError("La instancia está en estado %s; no se reintenta ni migra automáticamente" % previous)
            request = {k: p[k] for k in ("language", "sample_data", "library", "patron_categories", "administrator", "item_types", "circulation_rules")}
            request["marc_flavour"] = p["marcflavor"].upper()
            request.update(protocol=PROTOCOL, operation="initialize", apply=not module.check_mode)
            if module.check_mode:
                plan = _read_protocol(module, command, request, p["timeout"])
                complete = bool(plan.get("complete"))
                plan_result = dict(
                    changed=bool(plan.get("changed")), instance=instance, previous_state=previous, current_state=previous,
                    planned=True, partial=not complete, actions=plan.get("actions", []), state_info=plan.get("state_info"),
                    msg=("Modo de comprobación: las entidades y reglas declaradas se evaluaron con las APIs de Koha y se revirtieron."
                         if complete else
                         "Modo de comprobación: la instalación del esquema y los datos de Koha no se puede simular; "
                         "se informan las acciones previstas sin verificar conflictos de entidades."))
                _warn(module, plan.get("warnings"))
                module.exit_json(**plan_result)
            initializing = True
            result = _read_protocol(module, command, request, p["timeout"])
            current = result.get("current_state")
            if current != "initialized":
                raise InitializeError("La inicialización terminó sin alcanzar el estado initialized (observado: %s)" % current)
            success = dict(changed=bool(result.get("changed")), instance=instance,
                           previous_state=result.get("previous_state", previous), current_state=current,
                           actions=result.get("actions", []), validation=result.get("validation", {}),
                           state_info=result.get("state_info"),
                           msg="La inicialización de Koha y el onboarding finalizaron correctamente.")
            if module._diff:
                success["diff"] = {"before": previous, "after": current}
            _warn(module, result.get("warnings"))
            module.exit_json(**success)
    except (InitializeError, ModuleInputError, OSError, ValueError) as exc:
        details = getattr(exc, "details", {})
        message = str(exc)
        if initializing and details.get("indeterminate"):
            message += " " + _observe_after_failure(module, command, outcome)
        _warn(module, details.get("warnings"))
        module.fail_json(msg=message, instance=instance,
                         current_state=details.get("current_state", outcome["current_state"]),
                         previous_state=details.get("previous_state", outcome["previous_state"]),
                         state_info=details.get("state_info"),
                         changed=details.get("changed", outcome["changed"]), partial=details.get("partial", outcome["partial"]),
                         actions=details.get("actions", outcome["actions"]),
                         phase=details.get("phase"))


if __name__ == "__main__":
    main()
