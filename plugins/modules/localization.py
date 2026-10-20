# SPDX-License-Identifier: MIT-0
#!/usr/bin/python
"""Configure Koha OPAC and staff interface language preferences."""

DOCUMENTATION = r'''
---
module: localization
short_description: Configura idiomas y selectores de una instancia Koha
description:
  - Administra preferencias de idiomas de Staff y OPAC mediante las APIs Perl de Koha.
  - No instala traducciones, no inicializa la base de datos ni modifica servicios.
version_added: "1.3.0"
author: Jonas MZ
requirements:
  - Koha inicializado y accesible mediante koha-shell.
  - Traducciones requeridas instaladas previamente; use jmz.koha.translate.
options:
  instance:
    description: Instancia Koha sobre la que se aplican las preferencias.
    type: str
    required: true
  staff_languages:
    description: Idiomas instalados habilitados en Staff, en orden de prioridad; el primero es el predeterminado.
    type: list
    elements: str
  opac_languages:
    description: Idiomas instalados habilitados en OPAC, en orden de prioridad; el primero es el predeterminado.
    type: list
    elements: str
  opac_language_selector:
    description: Permite a los usuarios elegir idioma en OPAC.
    type: bool
  opac_selector_position:
    description: Posición del selector OPAC.
    type: str
    choices: [top, footer, both]
  staff_selector_position:
    description: Posición del selector Staff.
    type: str
    choices: [top, footer, both]
  state:
    description: Estado declarativo; localization administra preferencias estructurales y solo admite present.
    type: str
    choices: [present]
    default: present
  timeout:
    description: Límite en segundos para la consulta o actualización en koha-shell.
    type: int
    default: 120
'''

EXAMPLES = r'''
- name: Configurar español para OPAC y Staff
  jmz.koha.localization:
    instance: biblioteca
    staff_languages: [es-ES]
    opac_languages: [es-ES]
    opac_language_selector: false
  become: true

- name: Configurar instancia multilingüe
  jmz.koha.localization:
    instance: biblioteca
    staff_languages: [es-ES, en]
    opac_languages: [es-ES, en]
    opac_language_selector: true
    opac_selector_position: footer
    staff_selector_position: top
  become: true

- name: Cambiar solo el selector de OPAC
  jmz.koha.localization:
    instance: biblioteca
    opac_language_selector: true
  become: true
'''

RETURN = r'''
instance: {description: Instancia Koha consultada, returned: always, type: str}
koha_version: {description: Versión detectada desde la preferencia Version, returned: always, type: str}
staff_preference: {description: Preferencia de idioma Staff usada por esta instalación, returned: always, type: str}
before: {description: Valores reales anteriores de preferencias declaradas, returned: always, type: dict}
after: {description: Valores posteriores reales o proyectados en check mode, returned: always, type: dict}
updated_preferences: {description: Preferencias escritas en ejecución normal o previstas en check mode, returned: always, type: list}
planned: {description: after representa el resultado proyectado en check mode, returned: check mode, type: bool}
'''

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
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
HELPER_RE = re.compile(r"^/tmp/ansible-koha-localization-[0-9a-f]{32}/localization\.pl$")
OUTPUT_LIMIT = 6000
CONFIG_KEYS = ("staff_languages", "opac_languages", "opac_language_selector",
               "opac_selector_position", "staff_selector_position")


class LocalizationError(Exception):
    """A safe validation, protocol, or Koha execution error."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or {}


def validate_instance(value):
    if not isinstance(value, str) or not INSTANCE_RE.fullmatch(value):
        raise LocalizationError("instance debe ser un nombre Koha válido (1-11 minúsculas, números o guiones)")
    return value


def validate_language_list(value, key):
    """Validate language codes without changing their spelling or order."""
    if not isinstance(value, list) or not value:
        raise LocalizationError("%s debe ser una lista no vacía de códigos de idioma" % key)
    seen = set()
    result = []
    for code in value:
        if not isinstance(code, str) or not LANGUAGE_RE.fullmatch(code):
            raise LocalizationError("%s contiene un código malformado: %r" % (key, code))
        if code in seen:
            raise LocalizationError("%s contiene el idioma duplicado %s" % (key, code))
        seen.add(code)
        result.append(code)
    return result


def normalize_position(value):
    """Map the public selector positions to Koha's stored choices."""
    if value not in ("top", "footer", "both"):
        raise LocalizationError("la posición del selector debe ser top, footer o both")
    return value


def build_desired(params):
    desired = {}
    for key in ("staff_languages", "opac_languages"):
        if params.get(key) is not None:
            desired[key] = validate_language_list(params[key], key)
    if params.get("opac_language_selector") is not None:
        desired["opac_language_selector"] = bool(params["opac_language_selector"])
    for key in ("opac_selector_position", "staff_selector_position"):
        if params.get(key) is not None:
            desired[key] = normalize_position(params[key])
    if not desired:
        raise LocalizationError("declare al menos una preferencia de configuración además de instance y state")
    return desired


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
        raise LocalizationError("koha-shell excedió el límite de %s segundos" % timeout)
    except OSError as exc:
        raise LocalizationError("no se pudo ejecutar koha-shell: %s" % exc)
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, TypeError, ValueError):
        raise LocalizationError("el helper Perl no devolvió JSON válido (rc=%s)" % process.returncode,
                                {"stderr": stderr.decode("utf-8", "replace")[:OUTPUT_LIMIT]})
    if not isinstance(payload, dict) or payload.get("protocol") != PROTOCOL or not isinstance(payload.get("ok"), bool):
        raise LocalizationError("el helper Perl devolvió un protocolo incompleto o incompatible")
    if process.returncode != 0 or not payload["ok"]:
        error = payload.get("error") or {}
        raise LocalizationError("%s" % error.get("message", "falló la operación de Koha"),
                                payload.get("details") or {})
    required = ("koha_version", "staff_preference", "before", "after", "updated_preferences")
    if (any(key not in payload for key in required)
            or not isinstance(payload["koha_version"], str)
            or not isinstance(payload["staff_preference"], str)
            or not isinstance(payload["before"], dict)
            or not isinstance(payload["after"], dict)
            or not isinstance(payload["updated_preferences"], list)
            or any(not isinstance(name, str) for name in payload["updated_preferences"])):
        raise LocalizationError("el helper Perl devolvió una respuesta JSON incompleta o mal formada")
    return payload


def main():
    module = AnsibleModule(argument_spec=dict(
        instance=dict(type="str", required=True),
        staff_languages=dict(type="list", elements="str"),
        opac_languages=dict(type="list", elements="str"),
        opac_language_selector=dict(type="bool"),
        opac_selector_position=dict(type=choice_normalizer(["top", "footer", "both"]), choices=["top", "footer", "both"]),
        staff_selector_position=dict(type=choice_normalizer(["top", "footer", "both"]), choices=["top", "footer", "both"]),
        state=dict(type=choice_normalizer(["present"]), choices=["present"], default="present"),
        timeout=dict(type="int", default=120),
        _localization_helper=dict(type="path", required=True, no_log=True),
    ), supports_check_mode=True)
    p = module.params
    instance = p["instance"]
    try:
        validate_instance(instance)
        desired = build_desired(p)
        if p["timeout"] < 1:
            raise LocalizationError("timeout debe ser mayor que cero")
        conf = "/etc/koha/sites/%s/koha-conf.xml" % instance
        if not os.path.isfile(conf) or not os.access(conf, os.R_OK):
            raise LocalizationError("no existe una configuración legible para la instancia %s" % instance)
        if os.geteuid() != 0:
            raise LocalizationError("ejecute el módulo con become: true para usar koha-shell con los permisos de Koha")
        try:
            pwd.getpwnam(instance + "-koha")
        except KeyError:
            raise LocalizationError("no existe el usuario de sistema %s-koha" % instance)
        helper_arg = p["_localization_helper"]
        helper = os.path.realpath(helper_arg)
        if (os.path.islink(helper_arg) or helper != helper_arg or not os.path.isfile(helper)
                or not os.access(helper, os.R_OK) or not HELPER_RE.fullmatch(helper)):
            raise LocalizationError("no se encontró el helper temporal localization.pl de la colección")
        if not (os.stat(helper).st_mode & stat.S_IRUSR):
            raise LocalizationError("el helper Perl temporal no es legible")
        koha_shell = module.get_bin_path("koha-shell", required=False)
        if not koha_shell:
            raise LocalizationError("koha-shell no está disponible en el host administrado")
        # Staging path is generated by the collection action plugin and restricted above.
        command = [koha_shell, instance, "-c", "perl %s" % helper]
        request = {"protocol": PROTOCOL, "operation": "configure", "desired": desired,
                   "apply": not module.check_mode}
        payload = _read_protocol(command, request, p["timeout"])
        result = dict(instance=instance, koha_version=payload["koha_version"],
                      staff_preference=payload["staff_preference"], before=payload["before"],
                      after=payload["after"], updated_preferences=payload["updated_preferences"],
                      changed=bool(payload["updated_preferences"]),
                      planned=bool(module.check_mode))
        if module._diff:
            result["diff"] = {"before": payload["before"], "after": payload["after"]}
        result["msg"] = ("Cambios de localización proyectados." if module.check_mode and result["changed"]
                         else "La configuración de localización ya coincide." if not result["changed"]
                         else "Preferencias de localización actualizadas.")
        module.exit_json(**result)
    except (LocalizationError, OSError, ValueError, KeyError) as exc:
        details = getattr(exc, "details", {})
        module.fail_json(msg=str(exc), instance=instance,
                         updated_preferences=details.get("updated_preferences", []),
                         partial=details.get("partial", False))


if __name__ == "__main__":
    main()
