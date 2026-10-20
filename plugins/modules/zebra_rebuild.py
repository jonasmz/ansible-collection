# SPDX-License-Identifier: MIT-0
#!/usr/bin/python
"""Run a one-shot Zebra index update for a Koha instance."""

DOCUMENTATION = r'''
---
module: zebra_rebuild
short_description: Reconstruye de forma puntual los índices Zebra de una instancia Koha
description:
  - Invoca C(koha-rebuild-zebra) para exactamente una instancia, en modo incremental o completo, para bibliográficos, autoridades o ambos.
  - Es una operación imperativa; no administra los servicios Zebra ni del indexador.
  - Un comando terminado no demuestra la integridad de los índices ni informa el número de registros.
version_added: "1.3.0"
author: Jonas MZ
requirements:
  - Koha empaquetado para Debian/Ubuntu (C(koha-rebuild-zebra), C(koha-list), C(koha-shell), C(koha-zebra)).
  - Privilegios de root (use C(become=true)).
options:
  instance:
    description: Instancia Koha existente. Use un bucle para varias instancias.
    type: str
    required: true
  mode:
    description: C(incremental) procesa las actualizaciones pendientes; C(full) reconstruye por completo las colecciones elegidas.
    type: str
    choices: [incremental, full]
    default: incremental
  target:
    description: Colecciones Zebra a procesar.
    type: str
    choices: [all, biblios, authorities]
    default: all
  force:
    description: Pasa C(--force) al modo incremental cuando C(USE_INDEXER_DAEMON) está activo. Solo es válido con C(mode=incremental).
    type: bool
    default: false
  verbose:
    description: Número de banderas C(--verbose) (0 a 3). Use 0 con C(quiet=true).
    type: int
    choices: [0, 1, 2, 3]
    default: 1
  quiet:
    description: Pasa C(--quiet). No puede combinarse con un C(verbose) mayor que 0.
    type: bool
    default: false
  verify_search_engine:
    description: Lee la preferencia C(SearchEngine) y exige C(Zebra). Si no puede leerla, falla.
    type: bool
    default: true
  require_zebra_running:
    description: Exige que el servidor Zebra de la instancia esté activo. Este módulo nunca lo arranca.
    type: bool
    default: false
  timeout:
    description: Segundos máximos de cada pasada de C(koha-rebuild-zebra). Las demás consultas usan 60 segundos.
    type: int
    default: 3600
notes:
  - Una reconstrucción completa consume CPU, memoria, disco y E/S y puede reducir la disponibilidad de la búsqueda mientras se regeneran los índices.
  - La salida y el código de salida del comando no prueban la integridad funcional de los índices. Se clasifican los avisos y bloqueos de lock conocidos; la salida con código 0 y sin diagnósticos conocidos se da por completada, incluso si está vacía (C(quiet=true)).
  - Se comprueba que C(--help) del comando instalado anuncie cada opción solicitada.
  - Con C(USE_INDEXER_DAEMON) distinto de C(no), Koha omite el trabajo incremental salvo con C(force=true); el módulo lo informa con C(work_skipped=true) y sin fallar. Lee solo un valor estático simple de C(/etc/default/koha-common); un valor dinámico o ilegible falla de forma segura.
  - Se respeta el lock propio de Koha. El módulo no borra locks, no espera indefinidamente, no detiene servicios ni reintenta.
  - C(async) y C(poll) son controles de tarea de Ansible y sirven para reconstrucciones completas largas.
  - La operación es imperativa; una ejecución correcta informa C(changed=true), incluso un incremental que no encuentre registros.
  - En check mode se ejecutan las validaciones de solo lectura y se devuelve el comando previsto sin invocarlo.
'''

EXAMPLES = r'''
- name: Reconstrucción completa inicial tras arrancar Zebra
  jmz.koha.zebra_rebuild:
    instance: biblioteca
    mode: full
    require_zebra_running: true
  become: true

- name: Actualizar solo los índices bibliográficos
  jmz.koha.zebra_rebuild:
    instance: biblioteca
    target: biblios
  become: true

- name: Forzar el incremental de autoridades con el indexador activo
  jmz.koha.zebra_rebuild:
    instance: biblioteca
    target: authorities
    force: true
  become: true

- name: Reconstrucción completa silenciosa
  jmz.koha.zebra_rebuild:
    instance: biblioteca
    mode: full
    quiet: true
    verbose: 0
  become: true

- name: Reconstrucción larga bajo supervisión async
  jmz.koha.zebra_rebuild:
    instance: biblioteca
    mode: full
  async: 7200
  poll: 30
  become: true
'''

RETURN = r'''
instance: {description: Instancia seleccionada., returned: always, type: str}
mode: {description: Modo solicitado., returned: always, type: str}
target: {description: Colecciones solicitadas., returned: always, type: str}
status:
  description: Resultado normalizado, C(completed), C(skipped), C(blocked), C(failed) o C(unknown).
  returned: always
  type: str
executed: {description: Si se invocó la utilidad de reconstrucción., returned: always, type: bool}
work_skipped: {description: Si Koha o las reglas previas omitieron el trabajo solicitado., returned: always, type: bool}
skip_reason: {description: Explicación cuando se omitió el trabajo., returned: always, type: str}
command:
  description: Comandos previstos o ejecutados.
  returned: always
  type: list
  elements: list
rc: {description: Código de salida con un solo objetivo; nulo con varios o sin ejecución., returned: always, type: int}
duration: {description: Segundos totales de la reconstrucción; nulo si no se ejecutó., returned: always, type: float}
search_engine: {description: SearchEngine verificado; nulo si no se verificó., returned: always, type: str}
zebra_running: {description: Estado de Zebra si se exigió comprobarlo., returned: always, type: bool}
target_results:
  description: Resultado por objetivo. El recuento de registros es nulo porque la salida no es una interfaz estable.
  returned: always
  type: dict
stdout: {description: Salida estándar acotada de las invocaciones., returned: always, type: str}
stderr: {description: Salida de error acotada de las invocaciones., returned: always, type: str}
diagnostics: {description: Llamadas realizadas a comandos de Koha, con salida acotada., returned: when failed or after a run, type: list, elements: dict}
msg: {description: Resumen del resultado., returned: always, type: str}
'''

import contextlib
import re
import time

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import choice_normalizer
from ansible_collections.jmz.koha.plugins.module_utils import koha_service as svc


QUERY_TIMEOUT = 60
TARGET_FLAGS = {"biblios": "--biblios", "authorities": "--authorities"}
# Patterns that are specific enough to trust whatever the exit status says.
KNOWN_PATTERNS = (
    (re.compile(r"something went wrong rebuilding biblio indexes", re.I), "biblios", "failed"),
    (re.compile(r"something went wrong rebuilding authority indexes", re.I), "authorities", "failed"),
    (re.compile(r"unknown instance", re.I), None, "failed"),
    (re.compile(r"(?:unable|failed|could not|cannot|can't).{0,80}(?:obtain|acquire|create|get).{0,40}lock|lock.{0,50}(?:busy|unavailable|failed|already exists)", re.I), None, "blocked"),
    (re.compile(r"(?:continuing|proceeding|running).{0,50}without.{0,30}lock|without.{0,30}(?:a )?lock.{0,30}(?:continue|proceed|run)", re.I), None, "blocked"),
    (re.compile(r"(?:skipped|skipping).{0,80}(?:rebuild|index(?:ing)?|bibliographic|authority)", re.I), None, "skipped"),
)
# Generic words only count when the command also failed; record titles can contain them.
GENERIC_PATTERNS = (
    (re.compile(r"\b(?:fatal|error|failed|failure)\b", re.I), None, "failed"),
    (re.compile(r"\bwarning\b", re.I), None, "unknown"),
)


class RebuildError(Exception):
    """Unsafe or unverified rebuild request."""


def validate_arguments(p):
    if p["mode"] == "full" and p["force"]:
        raise RebuildError("force solo es válido con mode=incremental; mode=full ya ignora USE_INDEXER_DAEMON")
    if p["quiet"] and p["verbose"] > 0:
        raise RebuildError("quiet=true es incompatible con verbose mayor que 0; use verbose=0")
    if p["timeout"] <= 0:
        raise RebuildError("timeout debe ser positivo")


def validate_instance(module, instance, diagnostics):
    svc.check_instance(module, instance, diagnostics, QUERY_TIMEOUT)
    svc.require_root(module)


def check_search_engine(module, instance, diagnostics):
    value = svc.search_engine(module, instance, diagnostics, QUERY_TIMEOUT)
    if value != "Zebra":
        raise RebuildError("no se reconstruye Zebra en %s: SearchEngine es %s" % (instance, value))
    return value


def check_zebra_service(module, instance, diagnostics):
    daemon = svc.Daemon(module, "zebra", svc.find_command(module, "koha-zebra"), instance, diagnostics, QUERY_TIMEOUT)
    return daemon.status() == "started"


def inspect_indexer_configuration():
    """Read only a static USE_INDEXER_DAEMON assignment; koha-rebuild-zebra works incrementally only for exactly 'no'."""
    setting = svc.static_default("USE_INDEXER_DAEMON")
    return "disabled" if setting == "no" else "enabled_or_unset"


def validate_rebuild_request(module, p, diagnostics):
    validate_arguments(p)
    validate_instance(module, p["instance"], diagnostics)
    binary = svc.find_command(module, "koha-rebuild-zebra")
    help_rc, help_out, help_err = svc.run(module, [binary, "--help"], diagnostics, "inspect_cli_options", QUERY_TIMEOUT)
    help_text = help_out + "\n" + help_err
    expected = ["--full"] if p["mode"] == "full" else []
    expected += [TARGET_FLAGS[key] for key in ("biblios", "authorities") if p["target"] in ("all", key)]
    if p["force"]:
        expected.append("--force")
    if p["quiet"]:
        expected.append("--quiet")
    if p["verbose"]:
        expected.append("--verbose")
    if help_rc != 0:
        raise RebuildError("no se pudo consultar koha-rebuild-zebra --help (rc=%s): %s"
                           % (help_rc, svc.bounded(help_err or help_out).strip()))
    for option in expected:
        if not re.search(r"(?m)(?:^|\s)%s(?:\s|$|\|)" % re.escape(option), help_text):
            raise RebuildError("el koha-rebuild-zebra instalado no anuncia la opción requerida %s" % option)
    engine = check_search_engine(module, p["instance"], diagnostics) if p["verify_search_engine"] else None
    zebra = check_zebra_service(module, p["instance"], diagnostics) if p["require_zebra_running"] else None
    if p["require_zebra_running"] and not zebra:
        raise RebuildError("Zebra está detenido para %s; arránquelo con jmz.koha.zebra antes de reconstruir" % p["instance"])
    indexer = inspect_indexer_configuration() if p["mode"] == "incremental" else None
    return binary, engine, zebra, indexer


def build_rebuild_command(binary, p, target):
    argv = [binary]
    if p["mode"] == "full":
        argv.append("--full")
    if target in TARGET_FLAGS:
        argv.append(TARGET_FLAGS[target])
    if p["force"]:
        argv.append("--force")
    if p["quiet"]:
        argv.append("--quiet")
    argv.extend(["--verbose"] * p["verbose"])
    argv.append(p["instance"])
    return argv


def _empty_results():
    return {key: dict(status="unknown", executed=False, rc=None, records_processed=None, msg="No procesado")
            for key in ("biblios", "authorities")}


def parse_target_results(targets, outputs):
    results = _empty_results()
    for target in targets:
        rc, stdout, stderr = outputs[target]
        text = stdout + "\n" + stderr
        result = dict(status="unknown", executed=True, rc=rc, records_processed=None,
                      msg="El comando terminó, pero no se pudo verificar el resultado del índice")
        patterns = KNOWN_PATTERNS + (GENERIC_PATTERNS if rc != 0 else ())
        for pattern, affected, status in patterns:
            if pattern.search(text) and (affected is None or affected == target):
                result.update(status=status, msg="Diagnóstico reconocido de Koha: %s" % pattern.pattern)
                break
        else:
            if rc != 0:
                result.update(status="failed", msg="koha-rebuild-zebra devolvió un código de salida distinto de cero")
            else:
                # A quiet run prints nothing; koha-rebuild-zebra exits 0 only when it finished.
                result.update(status="completed", msg="koha-rebuild-zebra terminó con código 0 sin diagnósticos conocidos; no se comprobó la integridad del índice")
        results[target] = result
    return results


def classify_execution_result(target_results):
    statuses = [v["status"] for v in target_results.values() if v["executed"]]
    if not statuses:
        return "unknown"
    if "blocked" in statuses:
        return "blocked"
    if "failed" in statuses:
        return "failed"
    if "unknown" in statuses:
        return "unknown"
    if all(status == "skipped" for status in statuses):
        return "skipped"
    return "completed"


def build_module_result(p, commands, status, executed, work_skipped, skip_reason, engine,
                        zebra, target_results, stdout, stderr, duration, rc=None):
    return dict(instance=p["instance"], mode=p["mode"], target=p["target"], status=status,
                executed=executed, work_skipped=work_skipped, skip_reason=skip_reason,
                command=commands, rc=rc, duration=duration, search_engine=engine,
                zebra_running=zebra, target_results=target_results,
                stdout=svc.bounded(stdout), stderr=svc.bounded(stderr))


def run_rebuilds(module, p, targets, commands, diagnostics):
    """Run each target in turn and stop at the first one that cannot even be executed."""
    outputs, all_stdout, all_stderr, codes = {}, [], [], []
    start = time.monotonic()
    for target, argv in zip(targets, commands):
        try:
            rc, stdout, stderr = svc.run(module, argv, diagnostics, "rebuild_%s" % target, p["timeout"])
        except svc.ServiceError as exc:
            # A timed-out pass may already have modified indexes: report it as a failed target.
            rc, stdout, stderr = None, "", str(exc)
        outputs[target] = (rc, stdout, stderr)
        all_stdout.append(stdout)
        all_stderr.append(stderr)
        codes.append(rc)
        if rc is None:
            break
    return outputs, all_stdout, all_stderr, codes, max(0.0, time.monotonic() - start)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            instance=dict(type="str", required=True),
            mode=dict(type=choice_normalizer(["incremental", "full"]), choices=["incremental", "full"], default="incremental"),
            target=dict(type=choice_normalizer(["all", "biblios", "authorities"]), choices=["all", "biblios", "authorities"], default="all"),
            force=dict(type="bool", default=False),
            verbose=dict(type="int", choices=[0, 1, 2, 3], default=1),
            quiet=dict(type="bool", default=False),
            verify_search_engine=dict(type="bool", default=True),
            require_zebra_running=dict(type="bool", default=False),
            timeout=dict(type="int", default=3600),
        ), supports_check_mode=True,
    )
    p = module.params
    diagnostics = []
    targets = ["biblios", "authorities"] if p["target"] == "all" else [p["target"]]
    commands = []
    try:
        binary, engine, zebra, indexer = validate_rebuild_request(module, p, diagnostics)
        commands = [build_rebuild_command(binary, p, target) for target in targets]
        if p["mode"] == "incremental" and indexer == "enabled_or_unset" and not p["force"]:
            reason = ("USE_INDEXER_DAEMON no es 'no'; koha-rebuild-zebra omitiría el trabajo incremental porque lo hace el "
                      "demonio del indexador. Use force=true solo tras coordinarlo con el indexador.")
            result = build_module_result(p, commands, "skipped", False, True, reason, engine, zebra,
                                         _empty_results(), "", "", None)
            result.update(changed=False, msg=reason, diagnostics=diagnostics)
            module.exit_json(**result)
        if module.check_mode:
            results = _empty_results()
            for target in targets:
                results[target].update(msg="Se intentaría; check mode no inspecciona los registros pendientes")
            result = build_module_result(p, commands, "unknown", False, False, None, engine, zebra, results, "", "", None)
            result.update(changed=True, diagnostics=diagnostics,
                          msg="Check mode: se validó y planificó la operación %s de %s; no se garantizan cambios en los índices"
                          % (p["mode"], p["target"]))
            module.exit_json(**result)
        with svc.service_lock(p["instance"]):
            outputs, all_stdout, all_stderr, codes, duration = run_rebuilds(module, p, targets, commands, diagnostics)
    except (RebuildError, svc.ServiceError) as exc:
        result = build_module_result(p, commands, "failed", False, False, None, None, None, _empty_results(), "", "", None)
        result.update(changed=False, msg=str(exc), diagnostics=diagnostics)
        module.fail_json(**result)
    target_results = parse_target_results(list(outputs), outputs)
    status = classify_execution_result(target_results)
    result = build_module_result(p, commands, status, True, False, None, engine, zebra, target_results,
                                 "\n".join(all_stdout), "\n".join(all_stderr), duration,
                                 codes[0] if len(codes) == 1 else None)
    skipped_targets = [t for t in targets if target_results[t]["status"] == "skipped"]
    result["changed"] = status != "skipped"
    if skipped_targets:
        result.update(work_skipped=True, skip_reason="Koha informó trabajo omitido en: %s" % ", ".join(skipped_targets))
    result["diagnostics"] = diagnostics
    if status in ("failed", "blocked", "unknown"):
        result["msg"] = "Operación Zebra %s para %s: %s" % (status, p["instance"], ", ".join(
            "%s=%s" % (t, target_results[t]["status"]) for t in targets))
        module.fail_json(**result)
    result["msg"] = ("Koha informó que se omitió la pasada seleccionada para %s" % p["instance"] if status == "skipped" else
                     "koha-rebuild-zebra terminó para %s (%s); no se comprobó la integridad de los índices"
                     % (p["instance"], p["target"]))
    module.exit_json(**result)


if __name__ == "__main__":
    main()
