# SPDX-License-Identifier: MIT-0
#!/usr/bin/python
"""Manage Koha translations through koha-translate."""

DOCUMENTATION = r'''
---
module: translate
short_description: Administra de forma declarativa las traducciones de Koha
description:
  - Asegura que una traducción esté instalada o ausente mediante el comando oficial koha-translate.
  - El alcance en Debian es el árbol compartido de Koha, no una biblioteca individual.
  - No activa los idiomas en la interfaz; para eso use M(jmz.koha.localization).
version_added: "1.3.0"
author: Jonas MZ
requirements:
  - Koha empaquetado para Debian o Ubuntu con koha-translate, sus archivos auxiliares y los recursos de traducción (normalmente koha-l10n).
  - "Privilegios de root (use become: true)."
options:
  name:
    description: Código de idioma exacto de Koha, por ejemplo es-ES o fr-CA.
    type: str
    required: true
  state:
    description: Si la traducción debe estar instalada o ausente.
    type: str
    choices: [present, absent]
    default: present
  update:
    description: Regenera explícitamente una traducción instalada. Koha la elimina antes de reinstalarla, por lo que un fallo puede dejarla ausente.
    type: bool
    default: false
  verbose:
    description: Pide a koha-translate una salida detallada.
    type: bool
    default: false
  timeout:
    description: Segundos que puede ejecutarse cada llamada a koha-translate antes de ser terminada; una mutación que excede el límite se informa como parcial.
    type: int
    default: 600
notes:
  - Las traducciones se generan en el árbol compartido de Koha, no de forma privada para una instancia. Instalar y quitar limpian las cachés de las instancias habilitadas de manera global.
  - Los checkouts Git o de desarrollo de Koha (koha-translate --dev) no están soportados.
  - available solo comprueba un archivo PO de OPAC. Antes de instalar o actualizar, el módulo también ejecuta --check para los PO requeridos de MARC21, UNIMARC, OPAC, preferencias y personal; ninguna de las dos comprobaciones demuestra el funcionamiento en ejecución.
  - La actualización de Koha elimina y reinstala, y no es atómica. Primero se comprueban los PO requeridos y se verifica la lista de idiomas instalados al final; no se promete rollback.
  - En Koha 26.05.x install y remove limpian la caché; update no llama al ayudante de caché. Este módulo no agrega ninguna operación de caché.
  - Instalar plantillas no habilita OPACLanguages ni StaffInterfaceLanguages, no configura idiomas de usuario ni cambia la base de datos.
  - Las modificaciones se coordinan con un flock local bajo /run/lock. Las invocaciones externas de koha-translate no usan este lock.
  - La salida de koha-translate se devuelve con los bytes UTF-8 inválidos reemplazados, de modo que un comando que imprime texto no UTF-8 (fr-FR lo hace) ya no rompe el resultado.
  - update=true puede informar changed en cada ejecución; Koha no expone una comprobación fiable de la versión de las fuentes de traducción.
  - El inglés (en) está integrado y no puede instalarse, actualizarse ni quitarse.
  - Diseñado contra Koha 26.05.x y la interfaz upstream equivalente; valide el paquete instalado antes de usar otra rama.
  - El modo de comprobación hace solo consultas de lectura e informa la acción prevista. El modo diff muestra el estado semántico instalado, no el contenido de los PO o plantillas generados.
'''

EXAMPLES = r'''
- name: Instalar la traducción al español en el árbol compartido de Koha
  jmz.koha.translate:
    name: es-ES
    state: present
  become: true

- name: Asegurar que la traducción al francés esté ausente
  jmz.koha.translate:
    name: fr-FR
    state: absent
  become: true

- name: Regenerar explícitamente las plantillas en español
  jmz.koha.translate:
    name: es-ES
    state: present
    update: true
  become: true

- name: Previsualizar una instalación
  jmz.koha.translate:
    name: es-ES
    state: present
  check_mode: true
  diff: true
  become: true
'''

RETURN = r'''
name:
  description: Código de idioma pedido.
  returned: always
  type: str
state:
  description: Estado declarativo pedido.
  returned: always
  type: str
installed:
  description: Si el código exacto está instalado al final; en se trata como integrado.
  returned: always
  type: bool
available:
  description: Si Koha listó el código exacto como disponible, o nulo si no se consultó.
  returned: always
  type: bool
action_executed:
  description: Mutación realmente ejecutada, o nulo si no hubo ninguna.
  returned: always
  type: str
planned_action:
  description: Mutación prevista en check mode, o nulo si no hace falta cambio.
  returned: when check mode
  type: str
partial:
  description: Una mutación falló o fue terminada y las plantillas pueden haber quedado a medias.
  returned: when failed after a mutation
  type: bool
cmd:
  description: Lista argv segura del último comando o de la mutación prevista.
  returned: always
  type: list
  elements: str
rc:
  description: Código de retorno del último comando, o nulo si no se ejecutó ninguno.
  returned: always
  type: int
stdout:
  description: Salida estándar acotada del último comando.
  returned: always
  type: str
stderr:
  description: Salida de error acotada del último comando.
  returned: always
  type: str
msg:
  description: Resultado legible o la operación prevista.
  returned: always
  type: str
'''

import contextlib
import os
import re
import signal
import subprocess

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import ModuleInputError, choice_normalizer
from ansible_collections.jmz.koha.plugins.module_utils.koha_lock import exclusive_lock


LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
OUTPUT_LIMIT = 6000
LOCK_TIMEOUT = 30
REQUIRED_HELP_OPTIONS = ("--list", "--available", "--check", "--install", "--update", "--remove")
OBSERVE_TIMEOUT = 60


class TranslateError(Exception):
    """A safe validation, command, or verification error."""

    def __init__(self, message, result=None, timed_out=False):
        super().__init__(message)
        self.result = result
        self.timed_out = timed_out


class CommandTimeout(Exception):
    """A command was killed after running past its time limit."""

    def __init__(self, stdout, stderr):
        super().__init__("command timed out")
        self.stdout = stdout
        self.stderr = stderr


def _clean(value):
    """Return text that can always be serialized: invalid UTF-8 bytes become replacement characters."""
    return (value or "").encode("utf-8", "replace").decode("utf-8")


def _bounded(value):
    """Limit command output included in a module result."""
    return _clean(value)[:OUTPUT_LIMIT]


def validate_language(value):
    """Accept common Koha language identifiers and reject paths/options."""
    if not isinstance(value, str) or not LANGUAGE_RE.fullmatch(value):
        raise TranslateError("name debe ser un código de idioma como es-ES (letras y dígitos separados por guiones)")
    return value


def _run(argv, timeout):
    """Run argv with a stable locale and return (rc, stdout, stderr); kill its process group on timeout."""
    environment = dict(os.environ, LANG="C", LC_ALL="C", LC_MESSAGES="C")
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True, env=environment)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        raise CommandTimeout(stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace"))
    return process.returncode, stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace")


def _command(argv, operation, timeout):
    """Run argv and normalize errors and captured output."""
    try:
        rc, stdout, stderr = _run(argv, timeout)
    except CommandTimeout as exc:
        result = {"cmd": argv, "rc": None, "stdout": _bounded(exc.stdout), "stderr": _bounded(exc.stderr)}
        raise TranslateError("koha-translate %s excedió el límite de %s segundos" % (operation, timeout), result=result, timed_out=True)
    except OSError as exc:
        raise TranslateError("no se pudo ejecutar koha-translate para %s: %s" % (operation, exc))
    result = {"cmd": argv, "rc": rc, "stdout": _bounded(stdout), "stderr": _bounded(stderr)}
    if rc != 0:
        detail = (_clean(stderr) or _clean(stdout) or "sin salida de diagnóstico").strip()
        raise TranslateError("koha-translate %s falló (rc=%s): %s" % (operation, rc, _bounded(detail)), result=result)
    return result


def _query_languages(binary, mode, timeout):
    """Query and normalize exact installed or available language identifiers."""
    if mode == "installed":
        argv = [binary, "--list"]
    elif mode == "available":
        argv = [binary, "--list", "--available"]
    else:
        raise TranslateError("consulta de idiomas no admitida: %s" % mode)
    try:
        result = _command(argv, "language list query", timeout)
    except TranslateError as exc:
        # Koha 26.05.x uses `set -e` and ends `--list` with grep -v. When
        # there are no non-English translations installed, grep finds no
        # lines and the script exits 1 without diagnostics. Treat that exact
        # result as an empty installed-language list; other failures remain
        # errors. The available-language query has different semantics.
        result = exc.result
        if not (mode == "installed" and result and result.get("rc") == 1
                and not result.get("stdout") and not result.get("stderr")):
            raise
    languages = []
    seen = set()
    for raw in result["stdout"].splitlines():
        code = raw.strip()
        if not code:
            continue
        if not LANGUAGE_RE.fullmatch(code):
            raise TranslateError("koha-translate devolvió una salida %s inesperada: %s" % (mode, _bounded(code)))
        if code not in seen:
            seen.add(code)
            languages.append(code)
    return languages, result


def _check_po_files(binary, name, timeout):
    """Ask Koha to check the PO files required by its translation script."""
    argv = [binary, "--check", name]
    try:
        return _command(argv, "--check %s" % name, timeout)
    except TranslateError as exc:
        message = str(exc)
        if "not found" in message.lower() or "no such file" in message.lower():
            raise TranslateError("faltan archivos PO requeridos para %s; instale o repare los recursos de traducción (normalmente koha-l10n): %s" % (name, message))
        raise


def _verify_cli(binary, timeout):
    """Require installed help output to advertise the interface used here."""
    result = _command([binary, "--help"], "--help compatibility check", timeout)
    help_text = result["stdout"] + "\n" + result["stderr"]
    missing = [option for option in REQUIRED_HELP_OPTIONS if option not in help_text]
    if missing:
        raise TranslateError("el koha-translate instalado no anuncia las opciones requeridas: %s" % ", ".join(missing))
    return result


def _planned_argv(binary, action, name, verbose):
    """Build the native argv."""
    argv = [binary, "--" + action, name]
    if verbose:
        argv.append("--verbose")
    return argv


@contextlib.contextmanager
def _mutation_lock(wait=LOCK_TIMEOUT):
    """Serialize mutations of the shared translation tree; wait a bounded time for a busy lock."""
    try:
        with exclusive_lock("translate", "global",
                            "se agotó la espera del lock de traducciones; otra operación del módulo puede estar activa", wait=wait):
            yield
    except ModuleInputError as exc:
        raise TranslateError(str(exc))


def _need_action(state, installed, update):
    """Calculate the mutation needed for the requested state."""
    if state == "absent":
        return "remove" if installed else None
    if installed:
        return "update" if update else None
    return "install"


def _payload(name, state, installed, available, last, action=None, planned=None, msg=""):
    """Prepare consistent safe JSON output fields."""
    return {
        "name": name, "state": state, "installed": installed, "available": available,
        "action_executed": action, "planned_action": planned,
        "cmd": last.get("cmd", []) if last else [], "rc": last.get("rc") if last else None,
        "stdout": last.get("stdout", "") if last else "", "stderr": last.get("stderr", "") if last else "",
        "msg": msg,
    }


def _observe_installed(binary, name):
    """Best effort: whether ``name`` is installed after a failed mutation, or None when unknown."""
    try:
        codes, _ = _query_languages(binary, "installed", OBSERVE_TIMEOUT)
    except (TranslateError, OSError):
        return None
    return name in codes


def main():
    """Observe state, plan the minimum operation, and verify any mutation."""
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type="str", required=True),
            state=dict(type=choice_normalizer(["present", "absent"]), choices=["present", "absent"], default="present"),
            update=dict(type="bool", default=False),
            verbose=dict(type="bool", default=False),
            timeout=dict(type="int", default=600),
        ), supports_check_mode=True,
    )
    p = module.params
    name, state = p["name"], p["state"]
    update, verbose, timeout = p["update"], p["verbose"], p["timeout"]
    last = None
    installed = None
    available = None

    try:
        validate_language(name)
        if timeout <= 0:
            raise TranslateError("timeout debe ser positivo")
        if update and state != "present":
            raise TranslateError("update: true solo es válido con state: present")
        if name == "en" and state == "absent":
            raise TranslateError("el idioma inglés integrado (en) no se puede quitar")
        if name == "en" and update:
            raise TranslateError("el idioma inglés integrado (en) no se puede actualizar")

        binary = module.get_bin_path("koha-translate", required=False)
        if not binary or not os.path.isfile(binary) or not os.access(binary, os.X_OK):
            raise TranslateError("no se encontró koha-translate o no es ejecutable; instale el paquete de Koha que lo proporciona")
        last = _verify_cli(binary, timeout)
        if verbose and "--verbose" not in (last["stdout"] + last["stderr"]):
            raise TranslateError("installed koha-translate does not advertise required options: --verbose")
        if name == "en":
            result = _payload(name, state, True, None, last, msg="El inglés (en) es el idioma base integrado de Koha")
            if module._diff:
                result["diff"] = {"before": {"installed": True}, "after": {"installed": True}}
            module.exit_json(changed=False, **result)

        installed_codes, last = _query_languages(binary, "installed", timeout)
        installed = name in installed_codes
        action = _need_action(state, installed, update)
        if action in ("install", "update"):
            available_codes, last = _query_languages(binary, "available", timeout)
            available = name in available_codes
            if not available:
                raise TranslateError("el idioma %s no está disponible en los recursos de traducción locales; instale o repare koha-l10n" % name)
            last = _check_po_files(binary, name, timeout)

        if not action:
            result = _payload(name, state, installed, available, last,
                              msg="la traducción %s ya está %s" % (name, "instalada" if state == "present" else "ausente"))
            if module._diff:
                result["diff"] = {"before": {"installed": installed}, "after": {"installed": installed}}
            module.exit_json(changed=False, **result)

        mutation_argv = _planned_argv(binary, action, name, verbose)
        if module.check_mode:
            result = _payload(name, state, installed, available, last,
                              planned=action, msg="se ejecutaría %s de la traducción %s" % (action, name))
            result.update(cmd=mutation_argv, planned=True)
            if module._diff:
                result["diff"] = {"before": {"installed": installed}, "after": {"installed": action != "remove"}}
                if action == "update":
                    result["diff"]["regenerated"] = True
            module.exit_json(changed=True, **result)

        with _mutation_lock():
            # Re-read state under the module-local lock to avoid duplicate module work.
            installed_codes, last = _query_languages(binary, "installed", timeout)
            installed = name in installed_codes
            action = _need_action(state, installed, update)
            if action in ("install", "update"):
                available_codes, last = _query_languages(binary, "available", timeout)
                available = name in available_codes
                if not available:
                    raise TranslateError("el idioma %s dejó de estar disponible en los recursos de traducción locales" % name)
                last = _check_po_files(binary, name, timeout)
            if not action:
                result = _payload(name, state, installed, available, last,
                                  msg="la traducción %s alcanzó el estado pedido mientras se esperaba el lock" % name)
                module.exit_json(changed=False, **result)
            mutation_argv = _planned_argv(binary, action, name, verbose)
            try:
                last = _command(mutation_argv, "--%s %s" % (action, name), timeout)
            except TranslateError as exc:
                # A failed or killed koha-translate can leave templates half written, whatever the action.
                last = exc.result or last
                result = _payload(name, state, _observe_installed(binary, name), available, last, action=action, msg=str(exc))
                result["partial"] = True
                module.fail_json(changed=True, **result)
            action_result = last
            try:
                installed_codes, last = _query_languages(binary, "installed", timeout)
            except TranslateError as exc:
                last = exc.result or last
                result = _payload(name, state, None, available, last, action=action,
                                  msg="%s; no se pudo verificar el estado posterior y puede haber cambios parciales" % exc)
                result["partial"] = True
                module.fail_json(changed=True, **result)
            final_installed = name in installed_codes
            if final_installed != (action != "remove"):
                result = _payload(name, state, final_installed, available, last, action=action,
                                  msg="koha-translate terminó bien pero no se verificó el estado de instalación pedido")
                result["partial"] = True
                module.fail_json(changed=True, **result)

        result = _payload(name, state, final_installed, available, action_result, action=action,
                          msg="traducción %s %s y verificada" % (name, {"install": "instalada", "update": "actualizada", "remove": "eliminada"}[action]))
        if module._diff:
            result["diff"] = {"before": {"installed": installed}, "after": {"installed": final_installed}}
            if action == "update":
                result["diff"]["regenerated"] = True
        module.exit_json(changed=True, **result)

    except TranslateError as exc:
        last = exc.result or last
        module.fail_json(changed=False, name=name, state=state,
                         action_executed=None, planned_action=None,
                         cmd=last.get("cmd", []) if last else [], rc=last.get("rc") if last else None,
                         stdout=last.get("stdout", "") if last else "", stderr=last.get("stderr", "") if last else "",
                         installed=installed, available=available, msg=str(exc))


if __name__ == "__main__":
    main()
