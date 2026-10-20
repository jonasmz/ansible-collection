#!/usr/bin/python
# SPDX-License-Identifier: MIT-0
"""Manage packaged Koha SMTP defaults, email enablement and admin email."""

DOCUMENTATION = r'''
---
module: smtp
short_description: Configura el correo saliente de una instancia Koha existente
description:
  - Administra parcialmente el servidor SMTP XML, la bandera de correo y la preferencia KohaAdminEmailAddress.
  - Requiere que C(initialize) haya completado la base de datos; nunca crea instancias ni inicializa Koha.
  - El servidor predeterminado en base de datos tiene precedencia sobre el XML y bloquea cambios XML para evitar un falso éxito.
version_added: "1.3.0"
author: Jonas MZ
requirements:
  - Koha empaquetado para Debian/Ubuntu, koha-shell, koha-email-enable/disable y koha-preferences.
  - Las APIs Perl de Koha disponibles en el host.
options:
  instance:
    description: Instancia Koha existente; no tiene alias name.
    type: str
    required: true
  server:
    description: Campos parciales de yazgfs/config/smtp_server. Omitir conserva el valor actual; password vacío lo limpia explícitamente.
    type: dict
    options:
      host: {description: Host SMTP., type: str}
      port: {description: Puerto entre 1 y 65535., type: int}
      timeout: {description: Timeout positivo en segundos., type: int}
      ssl_mode: {description: Modo TLS; acepta mayúsculas/minúsculas y espacios externos., type: str, choices: [disabled, ssl, starttls]}
      user_name: {description: Usuario SMTP; cadena vacía limpia el usuario., type: str}
      password: {description: Secreto; cadena vacía limpia la contraseña., type: str, no_log: true}
      debug: {description: Depuración SMTP; desactivada por defecto., type: bool, default: false}
  admin_email_address:
    description: Valor de la preferencia global KohaAdminEmailAddress; no cambia si se omite.
    type: str
  enabled:
    description: Habilita o deshabilita el correo saliente Koha; no administra un MTA.
    type: bool
  timeout:
    description: Timeout de llamadas a koha-shell, en segundos.
    type: int
    default: 60
'''

EXAMPLES = r'''
- name: SMTP con STARTTLS
  jmz.koha.smtp:
    instance: biblioteca
    server: {host: smtp.example.org, port: 587, ssl_mode: starttls, user_name: notificaciones@example.org, password: "{{ vault_smtp_password }}"}
  become: true
  no_log: true

- name: SMTP con SSL
  jmz.koha.smtp:
    instance: biblioteca
    server: {host: smtp.example.org, port: 465, ssl_mode: ssl}
  become: true

- name: Preferencia administrativa solamente
  jmz.koha.smtp:
    instance: biblioteca
    admin_email_address: admin@example.org
  become: true

- name: Habilitar correo sin cambiar transporte
  jmz.koha.smtp: {instance: biblioteca, enabled: true}
  become: true

- name: Deshabilitar correo sin cambiar transporte
  jmz.koha.smtp: {instance: biblioteca, enabled: false}
  become: true

- name: Actualizar solo host y puerto
  jmz.koha.smtp:
    instance: biblioteca
    server: {host: smtp.example.org, port: 587}
  become: true

- name: Ejecutar después de initialize
  block:
    - jmz.koha.initialize:
        instance: biblioteca
        language: es-ES
        marc_flavour: MARC21
        library: {code: CENTRAL, name: Biblioteca Central}
        patron_categories: [{code: STAFF, description: Personal, type: S, enrolment_period: 1, default_privacy: default}, {code: ADULT, description: Adultos, type: A, enrolment_period: 1, default_privacy: default}]
        administrator: {username: admin, firstname: Admin, surname: Koha, cardnumber: ADMIN01, library: CENTRAL, category: STAFF, password: "{{ vault_admin_password }}"}
        item_types: [{code: BOOK, description: Libro}]
        circulation_rules: [{library: CENTRAL, category: ADULT, item_type: BOOK, rules: {issuelength: 14, lengthunit: days, maxissueqty: 5, renewalsallowed: 2}}]
    - jmz.koha.smtp:
        instance: biblioteca
        admin_email_address: admin@example.org
  become: true
  no_log: true

- name: Previsualizar cambios
  jmz.koha.smtp:
    instance: biblioteca
    server: {host: smtp.example.org, port: 587}
  check_mode: true
  diff: true
'''

RETURN = r'''
instance: {description: Instancia Koha., returned: always, type: str}
email_enabled: {description: Estado observado de email.enabled., returned: always, type: bool}
smtp_config_source: {description: Backend administrado para server., returned: always, type: str, sample: xml}
smtp_effective_source: {description: Fuente efectiva según Koha, o unknown si no se pudo determinar., returned: always, type: str}
smtp_changed: {description: Si cambió SMTP XML., returned: always, type: bool}
email_enabled_changed: {description: Si cambió el estado de correo., returned: always, type: bool}
admin_email_changed: {description: Si cambió KohaAdminEmailAddress., returned: always, type: bool}
admin_email_address: {description: Dirección deseada; omitida si no fue solicitada., returned: when supplied, type: str}
restart_required: {description: Configuración XML SMTP modificada; consumidores persistentes pueden retenerla en memoria., returned: always, type: bool}
restart_reason: {description: Razón para un reinicio explícito si aplica., returned: when restart_required, type: str}
warnings: {description: Advertencias sobre transporte sin cifrar y precedencia., returned: always, type: list}
'''

import email.utils
import json
import ipaddress
import os
import pwd
import re
import signal
import stat
import subprocess
import tempfile
import xml.parsers.expat

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import choice_normalizer


INSTANCE_RE = re.compile(r"^[a-z][a-z0-9-]{0,10}$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$")
FIELDS = ("host", "port", "timeout", "ssl_mode", "user_name", "password", "debug")


class SmtpError(Exception):
    pass


def _validate(params):
    instance = params["instance"]
    if not isinstance(instance, str) or not INSTANCE_RE.fullmatch(instance):
        raise SmtpError("instance debe tener 1-11 caracteres: minúsculas, números o guiones; debe comenzar por letra")
    server = params.get("server")
    if server is not None:
        unknown = set(server) - set(FIELDS)
        if unknown:
            raise SmtpError("server contiene campos no admitidos: %s" % ", ".join(sorted(unknown)))
        if "host" in server:
            host = server["host"]
            if not isinstance(host, str):
                raise SmtpError("server.host debe ser texto")
            labels = host.rstrip(".").split(".")
            try:
                ipaddress.ip_address(host.strip("[]"))
                valid_host = True
            except ValueError:
                valid_host = bool(host and len(host) <= 253 and all(
                    label and len(label) <= 63
                    and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label)
                    for label in labels))
            if not valid_host:
                raise SmtpError("server.host debe ser un hostname DNS válido")
        if "port" in server and (not isinstance(server["port"], int) or isinstance(server["port"], bool)
                                 or not 1 <= server["port"] <= 65535):
            raise SmtpError("server.port debe estar entre 1 y 65535")
        if "timeout" in server and (not isinstance(server["timeout"], int) or isinstance(server["timeout"], bool)
                                    or server["timeout"] <= 0):
            raise SmtpError("server.timeout debe ser positivo")
        if "ssl_mode" in server and server["ssl_mode"] not in ("disabled", "ssl", "starttls"):
            raise SmtpError("server.ssl_mode debe ser disabled, ssl o starttls")
        if "user_name" in server and (not isinstance(server["user_name"], str)
                                      or any(c in server["user_name"] for c in "\r\n\x00")):
            raise SmtpError("server.user_name no admite saltos de línea ni NUL")
        if "password" in server and (not isinstance(server["password"], str)
                                     or any(c in server["password"] for c in "\r\n\x00")):
            raise SmtpError("server.password no admite saltos de línea ni NUL")
        if "debug" in server and not isinstance(server["debug"], bool):
            raise SmtpError("server.debug debe ser booleano")
        if server.get("ssl_mode") == "disabled":
            # warning is added after inventory, since omitted values are preserved
            pass
    address = params.get("admin_email_address")
    if address is not None:
        if not isinstance(address, str):
            raise SmtpError("admin_email_address debe ser texto")
        parsed = email.utils.parseaddr(address)
        if (parsed[1] != address or not EMAIL_RE.fullmatch(address) or "@" not in address
                or any(c in address for c in "\r\n\x00 ")):
            raise SmtpError("admin_email_address debe ser una dirección de correo válida")
    if not isinstance(params.get("timeout", 60), int) or isinstance(params.get("timeout", 60), bool) or params.get("timeout", 60) <= 0:
        raise SmtpError("timeout debe ser positivo")


def _xml_inventory(raw):
    parser = xml.parsers.expat.ParserCreate()
    stack, starts, ends, elements, texts, complex_fields, counts = [], {}, {}, {}, {}, set(), {}
    smtp_path = ("yazgfs", "config", "smtp_server")
    server_count = [0]

    def start(name, attrs):
        if len(stack) == len(smtp_path) + 1 and tuple(stack[:len(smtp_path)]) == smtp_path:
            complex_fields.add(stack[-1])
        stack.append(name)
        current_path = tuple(stack)
        if current_path == smtp_path:
            server_count[0] += 1
        elif len(current_path) == len(smtp_path) + 1 and current_path[:len(smtp_path)] == smtp_path:
            counts[current_path[-1]] = counts.get(current_path[-1], 0) + 1
        starts[tuple(stack)] = parser.CurrentByteIndex

    def end(name):
        ends[tuple(stack)] = parser.CurrentByteIndex
        stack.pop()

    def character_data(value):
        path = tuple(stack)
        if len(path) == len(smtp_path) + 1 and path[:len(smtp_path)] == smtp_path:
            texts[path[-1]] = texts.get(path[-1], "") + value

    def comment(value):
        path = tuple(stack)
        if len(path) == len(smtp_path) + 1 and path[:len(smtp_path)] == smtp_path:
            complex_fields.add(path[-1])

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = character_data
    parser.CommentHandler = comment
    parser.Parse(raw, True)
    path = smtp_path
    for key in FIELDS:
        node = path + (key,)
        if node in starts:
            quote = None
            start_tag_end = starts[node]
            while start_tag_end < len(raw):
                byte = raw[start_tag_end]
                if quote is not None:
                    if byte == quote:
                        quote = None
                elif byte in (ord("\""), ord("'")):
                    quote = byte
                elif byte == ord(">"):
                    start_tag_end += 1
                    break
                start_tag_end += 1
            close_start = ends[node]
            content = raw[start_tag_end:close_start]
            if not content.strip():
                elements[key] = ((close_start, close_start) if b"\n" in content or b"\r" in content
                                 else (start_tag_end, close_start))
            elif b"\n" not in content and b"\r" not in content:
                elements[key] = (start_tag_end, close_start)
            else:
                leading = len(content) - len(content.lstrip())
                trailing = len(content) - len(content.rstrip())
                elements[key] = (start_tag_end + leading, close_start - trailing)
    if server_count[0] > 1 or any(count != 1 for count in counts.values()):
        raise SmtpError("koha-conf.xml contiene elementos SMTP duplicados")
    return raw, starts, ends, elements, path, texts, complex_fields


def _read_xml(path):
    if os.path.islink(path):
        raise SmtpError("koha-conf.xml no puede ser un enlace simbólico")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise SmtpError("koha-conf.xml debe ser un archivo regular")
        if st.st_mode & 0o037:
            raise SmtpError("koha-conf.xml tiene permisos demasiado abiertos; asegure permisos restrictivos (por ejemplo 0640)")
        chunks = []
        while True:
            chunk = os.read(fd, 131072)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
    finally:
        os.close(fd)
    try:
        inventory = _xml_inventory(raw)
    except xml.parsers.expat.ExpatError:
        raise SmtpError("koha-conf.xml no contiene XML válido")
    if ("yazgfs", "config") not in inventory[1]:
        raise SmtpError("koha-conf.xml no contiene yazgfs/config")
    return raw, st, inventory


def _current_values(raw, inventory):
    return {key: value.strip() if "\n" in value or "\r" in value else value
            for key, value in inventory[5].items()}


def _updated_xml(raw, inventory, requested):
    values = _current_values(raw, inventory)
    normalized = {k: ("1" if v else "0") if k == "debug" else str(v) for k, v in requested.items()}
    changes = {k: normalized[k] for k in requested if values.get(k) != normalized[k]}
    if not changes:
        return raw, False
    elements = inventory[3]
    edits = []
    for key, value in changes.items():
        if key in inventory[6]:
            raise SmtpError("El elemento smtp_server/%s contiene nodos o comentarios; no se reemplazó" % key)
        escaped = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if key in elements:
            a, b = elements[key]
            edits.append((a, b, escaped.encode("utf-8")))
        else:
            raise SmtpError("Falta el elemento smtp_server/%s; no se alterará la estructura XML" % key)
    result = raw
    for a, b, replacement in sorted(edits, reverse=True):
        result = result[:a] + replacement + result[b:]
    try:
        _xml_inventory(result)
    except xml.parsers.expat.ExpatError:
        raise SmtpError("La actualización propuesta no produjo XML válido")
    return result, True


def _atomic_replace(path, content, original_stat):
    directory = os.path.dirname(path)
    fd, temporary = tempfile.mkstemp(prefix=".koha-conf-smtp-", dir=directory)
    backup = temporary + ".recovery"
    preserve_backup = False
    descriptor_open = True
    try:
        current_stat = os.stat(path, follow_symlinks=False)
        if (not stat.S_ISREG(current_stat.st_mode)
                or current_stat.st_dev != original_stat.st_dev or current_stat.st_ino != original_stat.st_ino):
            raise SmtpError("koha-conf.xml cambió durante la operación; no se reemplazó")
        os.fchown(fd, original_stat.st_uid, original_stat.st_gid)
        os.fchmod(fd, stat.S_IMODE(original_stat.st_mode))
        with os.fdopen(fd, "wb", closefd=True) as stream:
            descriptor_open = False
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(path, backup, follow_symlinks=False)
        backup_stat = os.stat(backup, follow_symlinks=False)
        if backup_stat.st_dev != original_stat.st_dev or backup_stat.st_ino != original_stat.st_ino:
            raise SmtpError("koha-conf.xml cambió durante la operación; no se reemplazó")
        os.replace(temporary, path)
        dir_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        os.unlink(backup)
    except Exception:
        if os.path.exists(backup):
            try:
                os.replace(backup, path)
            except OSError:
                preserve_backup = True
                raise SmtpError("No se pudo restaurar koha-conf.xml; se conservó la copia de recuperación %s" % backup)
        raise
    finally:
        if descriptor_open:
            os.close(fd)
        for candidate in (temporary, None if preserve_backup else backup):
            try:
                if candidate:
                    os.unlink(candidate)
            except FileNotFoundError:
                pass


def _run(command, data=None, timeout=60):
    process = subprocess.Popen(command, stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True,
                               start_new_session=True)
    try:
        out, err = process.communicate(data, timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise SmtpError("koha-shell excedió el timeout configurado")
    return process.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def _koha_probe(module, instance, helper, timeout):
    koha_shell = module.get_bin_path("koha-shell", required=False)
    if not koha_shell:
        raise SmtpError("koha-shell no está disponible")
    if (os.path.islink(helper) or not os.path.isfile(helper)
            or not re.fullmatch(r"/tmp/ansible-koha-smtp-[0-9a-f]{32}/smtp_probe\.pl", helper)
            or os.path.realpath(helper) != helper):
        raise SmtpError("Helper de inspección Koha inválido")
    command = [koha_shell, "-c", "perl %s" % helper, instance]
    rc, out, _ = _run(command, b"", timeout)
    fields = out.strip().split("\t")
    if rc != 0 or len(fields) != 4 or fields[0] != "ok":
        raise SmtpError("Falló la inspección de APIs Koha o una API requerida no está disponible")
    return {"ok": True, "needs_install": fields[1] == "1", "database_default": fields[2] == "1",
            "effective_source": fields[3], "has_context": True, "has_smtp_api": True}


def _preference(module, instance, operation, value=None, timeout=60):
    koha_shell = module.get_bin_path("koha-shell", required=False)
    prefs = "/usr/share/koha/bin/admin/koha-preferences"
    if not koha_shell or not os.path.isfile(prefs) or not os.access(prefs, os.X_OK):
        raise SmtpError("koha-shell o /usr/share/koha/bin/admin/koha-preferences no está disponible")
    if operation == "get":
        command = [koha_shell, "-c", prefs + " get KohaAdminEmailAddress", instance]
        rc, out, _ = _run(command, timeout=timeout)
        if rc != 0:
            raise SmtpError("koha-preferences get falló (rc=%s)" % rc)
        return out.rstrip("\r\n")
    # koha-preferences load explicitly reads YAML from STDIN. JSON string syntax is YAML-safe.
    command = [koha_shell, "-c", prefs + " load", instance]
    yaml_input = ("KohaAdminEmailAddress: " + json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8")
    rc, _, _ = _run(command, yaml_input, timeout)
    if rc == 0:
        return
    raise SmtpError("koha-preferences load falló (rc=%s)" % rc)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            instance=dict(type="str", required=True),
            server=dict(type="dict", options=dict(
                host=dict(type="str"), port=dict(type="int"), timeout=dict(type="int"),
                ssl_mode=dict(type=choice_normalizer(["disabled", "ssl", "starttls"]), choices=["disabled", "ssl", "starttls"]),
                user_name=dict(type="str"), password=dict(type="str", no_log=True), debug=dict(type="bool", default=False),
            )),
            admin_email_address=dict(type="str"), enabled=dict(type="bool"), timeout=dict(type="int", default=60),
            _smtp_probe=dict(type="path", required=True, no_log=True),
        ), supports_check_mode=True,
    )
    p = module.params
    instance = p["instance"]
    try:
        _validate(p)
        if os.geteuid() != 0:
            raise SmtpError("Ejecute con become: true para administrar la configuración Koha")
        try:
            pwd.getpwnam(instance + "-koha")
        except KeyError:
            raise SmtpError("La instancia Koha '%s' no existe (falta su usuario de sistema)" % instance)
        conf = "/etc/koha/sites/%s/koha-conf.xml" % instance
        instance_dir = "/etc/koha/sites/%s" % instance
        if os.path.islink(instance_dir) or os.path.realpath(instance_dir) != instance_dir:
            raise SmtpError("El directorio de configuración no corresponde a la instancia solicitada")
        if not os.path.isfile(conf) or os.path.islink(conf) or not os.access(conf, os.R_OK | os.W_OK):
            raise SmtpError("La configuración de la instancia '%s' no existe o no es accesible" % instance)
        data_dir = "/var/lib/koha/%s" % instance
        if os.path.islink(data_dir) or os.path.realpath(data_dir) != data_dir or not os.path.isdir(data_dir):
            raise SmtpError("El directorio de datos de la instancia no existe o es un enlace simbólico")
        enabled_path = os.path.join(data_dir, "email.enabled")
        if os.path.islink(enabled_path) or (os.path.exists(enabled_path) and not os.path.isfile(enabled_path)):
            raise SmtpError("email.enabled no puede ser un enlace simbólico")
        xml_raw, xml_stat, inventory = _read_xml(conf)
        current_xml = _current_values(xml_raw, inventory)
        desired_xml, xml_changed = _updated_xml(xml_raw, inventory, p.get("server") or {})
        probe = _koha_probe(module, instance, p["_smtp_probe"], p["timeout"])
        if probe.get("needs_install"):
            raise SmtpError("La instancia '%s' todavía no tiene la base de datos Koha inicializada. Ejecute initialize antes de smtp." % instance)
        if not probe.get("has_smtp_api") or not probe.get("has_context"):
            raise SmtpError("La versión instalada de Koha no ofrece las APIs requeridas")
        effective_source = probe.get("effective_source", "unknown")
        warnings = []
        if p.get("server") is not None and probe.get("database_default"):
            raise SmtpError("La instancia tiene un SMTP predeterminado persistido en la base de datos; Koha lo prioriza sobre XML. No se modificó ningún estado.")
        enabled_before = os.path.exists(enabled_path)
        if not os.path.exists(enabled_path) and not os.path.isdir(data_dir):
            raise SmtpError("No se puede determinar el estado email.enabled")
        admin_current = None
        if p.get("admin_email_address") is not None:
            admin_current = _preference(module, instance, "get", timeout=p["timeout"])
        admin_changed = p.get("admin_email_address") is not None and admin_current != p["admin_email_address"]
        enabled_changed = p.get("enabled") is not None and enabled_before != p["enabled"]
        # Resolve every external interface before the first mutation so a missing
        # Koha utility cannot leave an earlier responsibility partially applied.
        if p.get("admin_email_address") is not None:
            prefs = "/usr/share/koha/bin/admin/koha-preferences"
            if not os.path.isfile(prefs) or not os.access(prefs, os.X_OK):
                raise SmtpError("/usr/share/koha/bin/admin/koha-preferences no está disponible")
        if enabled_changed:
            executable = module.get_bin_path("koha-email-enable" if p["enabled"] else "koha-email-disable", required=False)
            if not executable:
                raise SmtpError("No está disponible el comando oficial para cambiar el estado de correo")
        wanted_tls = (p.get("server") or {}).get("ssl_mode", current_xml.get("ssl_mode"))
        if wanted_tls == "disabled" and effective_source != "database":
            warnings.append("SMTP usa transporte sin cifrado; las credenciales y el correo pueden viajar sin protección TLS.")
        if probe.get("database_default"):
            warnings.append("El servidor SMTP predeterminado efectivo procede de la base de datos; la configuración XML no lo reemplaza.")
        changed = bool(xml_changed or enabled_changed or admin_changed)
        diff = {"before": {}, "after": {}}
        if p.get("server") is not None:
            for key in p["server"]:
                a = current_xml.get(key)
                b = ("<redacted>" if key == "password" else str(p["server"][key]))
                diff["before"][key] = "<redacted>" if key == "password" and a is not None else a
                diff["after"][key] = b
        if p.get("enabled") is not None:
            diff["before"]["email_enabled"] = enabled_before
            diff["after"]["email_enabled"] = p["enabled"]
        if p.get("admin_email_address") is not None:
            diff["before"]["admin_email_address"] = admin_current
            diff["after"]["admin_email_address"] = p["admin_email_address"]
        if module.check_mode:
            module.exit_json(changed=changed, instance=instance, email_enabled=p.get("enabled", enabled_before),
                             smtp_config_source="xml", smtp_effective_source=effective_source,
                             smtp_changed=xml_changed, email_enabled_changed=enabled_changed,
                             admin_email_changed=admin_changed,
                             admin_email_address=p.get("admin_email_address"), restart_required=xml_changed,
                             restart_reason="smtp_config_changed" if xml_changed else None,
                             warnings=warnings, diff=diff if module._diff else None)
        actions = []
        if xml_changed:
            _atomic_replace(conf, desired_xml, xml_stat)
            actions.append("smtp_xml_updated")
            changed = True
        if admin_changed:
            _preference(module, instance, "set", p["admin_email_address"], p["timeout"])
            actions.append("admin_email_updated")
            changed = True
            if _preference(module, instance, "get", timeout=p["timeout"]) != p["admin_email_address"]:
                raise SmtpError("Koha no confirmó KohaAdminEmailAddress después de escribirla")
        if enabled_changed:
            command_name = "koha-email-enable" if p["enabled"] else "koha-email-disable"
            executable = module.get_bin_path(command_name, required=False)
            rc, _, _ = _run([executable, instance], timeout=p["timeout"])
            actions.append("email_enabled" if p["enabled"] else "email_disabled")
            changed = True
            state_verified = (os.path.isfile(enabled_path) and not os.path.islink(enabled_path)) if p["enabled"] \
                else not os.path.lexists(enabled_path)
            if rc != 0 or not state_verified:
                raise SmtpError("%s no dejó email.enabled en el estado solicitado" % command_name)
        module.exit_json(changed=changed, instance=instance, email_enabled=p.get("enabled", enabled_before),
                         smtp_config_source="xml", smtp_effective_source=effective_source,
                         smtp_changed=xml_changed, email_enabled_changed=enabled_changed,
                         admin_email_changed=admin_changed, admin_email_address=p.get("admin_email_address"),
                         restart_required=xml_changed, restart_reason="smtp_config_changed" if xml_changed else None,
                         warnings=warnings, actions=actions, diff=diff if module._diff else None,
                         msg="Configuración de correo Koha inspeccionada y aplicada.")
    except (SmtpError, OSError, ValueError, UnicodeError, xml.parsers.expat.ExpatError) as exc:
        module.fail_json(msg=str(exc), instance=instance, smtp_effective_source="unknown", changed=bool(locals().get("actions")),
                         partial=bool(locals().get("actions")), actions=locals().get("actions", []),
                         smtp_changed=locals().get("xml_changed", False),
                         email_enabled_changed=locals().get("enabled_changed", False),
                         admin_email_changed=locals().get("admin_changed", False))


if __name__ == "__main__":
    main()
