# SPDX-License-Identifier: MIT-0
#!/usr/bin/python
"""Create Koha instances using the packaged koha-create command."""

DOCUMENTATION = r'''
---
module: instance
short_description: Crea de forma declarativa una instancia Koha
description:
  - Ejecuta koha-create solo cuando la instancia está ausente o en etapa request.
  - Usa un archivo configfile temporal privado para evitar el límite de argumentos y proteger secretos de SMTP y RabbitMQ.
  - La compatibilidad de opciones depende de la versión instalada de koha-create.
version_added: "1.0.0"
author: Jonas MZ
options:
  name:
    description: Nombre Unix/DNS de la instancia; 1-11 caracteres.
    type: str
    required: true
  state:
    description: present crea/configura; absent elimina archivos con doble confirmacion.
    type: str
    choices: [present, absent]
    default: present
  db_mode:
    description: Modo nativo --create-db, --request-db, --populate-db o --use-db.
    type: str
    choices: [create, request, populate, use]
    default: create
  marcflavor:
    description: Mapea --marcflavor; acepta mayúsculas/minúsculas y normaliza a minúsculas. Valores admitidos marc21 o unimarc.
    type: str
    choices: [marc21, unimarc]
  zebralang:
    description: Mapea --zebralang. Default nativo en la referencia, en.
    type: str
    choices: [cs, el, en, es, fr, nb, ru, uk]
  elasticsearch_server:
    description: Mapea --elasticsearch-server. No cambia el motor Zebra a Elasticsearch.
    type: str
  memcached_servers:
    description: Lista convertida a --memcached-servers equivalente (CLO_MEMCACHED_SERVERS).
    type: list
    elements: str
  memcached_prefix:
    description: Mapea --memcached-prefix; se concatena con el nombre de instancia.
    type: str
  memcached_enabled:
    description: Variable USE_MEMCACHED del configfile; si se omite hereda Koha global.
    type: bool
  enable_sru:
    description: Habilita SRU/Z39.50 en Zebra; por defecto no se impone.
    type: bool
    default: false
  sru_port:
    description: Mapea --sru-port. Puerto nativo predeterminado 7090.
    type: int
  dbhost:
    description: Mapea --dbhost; la referencia autodetecta el host si se omite.
    type: str
  database:
    description: Mapea --database; máximo nativo 64 caracteres.
    type: str
  passwdfile:
    description: Archivo remoto en formato Koha name:user:password:database:host. No combinado con db_credentials.
    type: path
  db_credentials:
    description: Credenciales convertidas a passwdfile privado efímero; username/password no se devuelven.
    type: dict
    no_log: true
    options:
      username: {description: Usuario de base de datos que se escribirá en el archivo privado de credenciales., type: str, required: true}
      password: {description: Contraseña de base de datos. Se mantiene fuera de argv y de la salida del módulo., type: str, required: true, no_log: true}
  defaultsql:
    description: Mapea --defaultsql; puede ser SQL comprimido compatible con zcat. Solo create/populate.
    type: path
  adminuser:
    description: Mapea --adminuser; ID del borrower actualizado al usar defaultsql en create/populate.
    type: int
  configfile:
    description: Archivo de configuración Bash confiable del administrador; se incluye antes de los overrides generados.
    type: path
  template_cache_dir:
    description: Mapea --template-cache-dir; default nativo /var/cache/koha/name/templates.
    type: path
  timezone:
    description: Mapea --timezone; se omite para heredar el default vacío.
    type: str
  upload_path:
    description: Mapea --upload-path; default nativo /var/lib/koha/name/uploads.
    type: path
  tmp_path:
    description: Mapea --tmp-path; default nativo /var/lib/koha/name/tmp.
    type: path
  smtp:
    description: Opciones nativas SMTP agrupadas. Si se omite, Koha global/default permanece.
    type: dict
    no_log: true
    options:
      host: {description: Host SMTP pasado a la configuración nativa de Koha., type: str}
      port: {description: Puerto SMTP., type: int}
      timeout: {description: Timeout SMTP en segundos., type: int}
      ssl_mode: {description: Modo TLS nativo; disabled, ssl o starttls., type: str, choices: [disabled, ssl, starttls]}
      username: {description: Usuario SMTP., type: str}
      password: {description: Contraseña SMTP; se mantiene fuera de argv y de la salida del módulo., type: str, no_log: true}
      debug: {description: Activa el diagnóstico SMTP de Koha cuando se solicita explícitamente., type: bool}
  message_broker:
    description: Opciones nativas RabbitMQ; el módulo no instala ni configura el broker.
    type: dict
    no_log: true
    options:
      host: {description: Host del broker de mensajes; no instala ni configura el servicio., type: str}
      port: {description: Puerto del broker según el protocolo usado por Koha., type: int}
      username: {description: Usuario del broker., type: str}
      password: {description: Contraseña del broker; se mantiene fuera de argv y de la salida del módulo., type: str, no_log: true}
      vhost: {description: Virtual host del broker., type: str}
  letsencrypt:
    description: Habilita Let's Encrypt local; requiere paquete, comando y mod_ssl instalados.
    type: bool
    default: false
  tls_termination:
    description: Indica si TLS termina en Apache o en un proxy frontal. letsencrypt requiere local.
    type: str
    choices: [local, proxy]
  remove_database:
    description: Con state=absent permite borrar la DB koha_<name>; por defecto se conserva.
    type: bool
    default: false
  purge_data:
    description: Con state=absent elimina /var/lib/koha/<name> y spool mediante --purge-all.
    type: bool
    default: false
  confirm_name:
    description: Debe repetir name exactamente para operaciones destructivas.
    type: str
  confirm_data_loss:
    description: Segunda confirmacion explicita requerida para operaciones destructivas.
    type: bool
    default: false
  repair:
    description: Reconstruye configuracion partial con koha-remove --keep-mysql y koha-create --use-db.
    type: bool
    default: false
  reconfigure:
    description: Reconstruye la configuracion con parametros nuevos, preservando la DB.
    type: bool
    default: false
  keep_cookies:
    description: Mapea opciones repetibles --keep-cookie; nombres de cookie seguros.
    type: list
    elements: str
  vhosts:
    description: Overrides de DOMAIN/OPACPORT/OPACPREFIX/OPACSUFFIX/INTRAPORT/INTRAPREFIX/INTRASUFFIX.
    type: dict
    options:
      domain: {description: Sufijo común de dominio Koha, por ejemplo .example.org., type: str}
      opac_port: {description: Puerto configurado para el VirtualHost OPAC., type: int}
      opac_prefix: {description: Prefijo agregado al nombre de host OPAC., type: str}
      opac_suffix: {description: Sufijo agregado al nombre de host OPAC., type: str}
      staff_port: {description: Puerto configurado para el VirtualHost de personal., type: int}
      staff_prefix: {description: Prefijo agregado al nombre de host de personal., type: str}
      staff_suffix: {description: Sufijo agregado al nombre de host de personal., type: str}
  db_request_path:
    description: Ruta persistente con modo 0600 para la solicitud generada en db_mode=request.
    type: path
  koha_create_path:
    description: Ruta explícita del binario si no está en una ubicación estándar.
    type: path
  koha_remove_path:
    description: Ruta explícita de koha-remove si no está en PATH.
    type: path
'''

EXAMPLES = r'''
- name: Crear instancia Koha
  jmz.koha.instance:
    name: biblioteca
    db_mode: create
    marcflavor: marc21
    zebralang: es
  become: true

- name: Crear detrás de HAProxy
  jmz.koha.instance:
    name: biblioteca
    db_mode: create
    vhosts:
      domain: .example.org
      opac_port: 80
      staff_port: 80
      staff_suffix: -admin
    memcached_enabled: true
    smtp:
      host: smtp.example.org
      port: 587
      ssl_mode: starttls
      username: biblioteca@example.org
      password: "{{ vault_smtp_password }}"
  become: true
  no_log: true

- name: Usar DB existente
  jmz.koha.instance:
    name: biblioteca
    db_mode: use
    database: koha_biblioteca
    db_credentials:
      username: koha_biblioteca
      password: "{{ vault_koha_db_password }}"
  become: true
  no_log: true

- name: Solicitar DB externa
  jmz.koha.instance:
    name: biblioteca
    db_mode: request
    db_request_path: /root/koha-db-requests/biblioteca-db-request.txt
  become: true
  no_log: true

- name: Completar solicitud previa
  jmz.koha.instance:
    name: biblioteca
    db_mode: populate
  become: true
  no_log: true

- name: Reconfigurar una instancia preservando la DB
  jmz.koha.instance:
    name: biblioteca
    reconfigure: true
    confirm_name: biblioteca
    confirm_data_loss: true
    vhosts:
      domain: .example.org
      staff_suffix: -admin
  become: true

- name: Retirar instancia, preservando DB y datos
  jmz.koha.instance:
    name: biblioteca
    state: absent
    confirm_name: biblioteca
    confirm_data_loss: true
  become: true

- name: Crear con TLS terminado localmente
  jmz.koha.instance:
    name: biblioteca
    db_mode: create
    vhosts:
      domain: .example.org
    letsencrypt: true
    tls_termination: local
  become: true
'''

RETURN = r'''
name: {description: Nombre validado, returned: always, type: str}
state: {description: Estado inspeccionado o previsto, returned: always, type: str, sample: present}
db_mode: {description: Modo utilizado, returned: always, type: str}
config_path: {description: Ruta esperada del koha-conf.xml, returned: always, type: str}
apache_site_path: {description: Ruta esperada del sitio Apache, returned: always, type: str}
opac_hostname: {description: Host calculado si se definió vhosts, returned: when vhosts is defined, type: str}
staff_hostname: {description: Host calculado si se definió vhosts, returned: when vhosts is defined, type: str}
request_file: {description: Ruta segura de solicitud de DB; nunca su contenido, returned: when db_mode=request, type: str}
actions: {description: Acciones planeadas o ejecutadas, returned: always, type: list}
notices: {description: Notas informativas o de compatibilidad; nunca incluyen secretos., returned: always, type: list}
'''

import hashlib
import json
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import (
    ModuleInputError, build_argv, db_password_is_safe, inspect_state, normalize_marcflavor, render_config, validate_params,
)


ARGUMENT_SPEC = {
    "name": {"type": "str", "required": True}, "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
    "db_mode": {"type": "str", "default": "create", "choices": ["create", "request", "populate", "use"]},
    "marcflavor": {"type": normalize_marcflavor, "choices": ["marc21", "unimarc"]},
    "zebralang": {"type": "str", "choices": ["cs", "el", "en", "es", "fr", "nb", "ru", "uk"]},
    "elasticsearch_server": {"type": "str"}, "memcached_servers": {"type": "list", "elements": "str"},
    "memcached_prefix": {"type": "str"}, "memcached_enabled": {"type": "bool"}, "enable_sru": {"type": "bool", "default": False},
    "sru_port": {"type": "int"}, "dbhost": {"type": "str"}, "database": {"type": "str"},
    "passwdfile": {"type": "path"}, "defaultsql": {"type": "path"}, "adminuser": {"type": "int"},
    "configfile": {"type": "path"}, "template_cache_dir": {"type": "path"}, "timezone": {"type": "str"},
    "upload_path": {"type": "path"}, "tmp_path": {"type": "path"}, "smtp": {"type": "dict", "no_log": True, "options": {
        "host": {"type": "str"}, "port": {"type": "int"}, "timeout": {"type": "int"},
        "ssl_mode": {"type": "str", "choices": ["disabled", "ssl", "starttls"]}, "username": {"type": "str"},
        "password": {"type": "str", "no_log": True}, "debug": {"type": "bool"}}},
    "message_broker": {"type": "dict", "no_log": True, "options": {
        "host": {"type": "str"}, "port": {"type": "int"}, "username": {"type": "str"},
        "password": {"type": "str", "no_log": True}, "vhost": {"type": "str"}}},
    "db_credentials": {"type": "dict", "no_log": True, "options": {"username": {"type": "str", "required": True}, "password": {"type": "str", "required": True, "no_log": True}}},
    "letsencrypt": {"type": "bool", "default": False}, "tls_termination": {"type": "str", "choices": ["local", "proxy"]},
    "remove_database": {"type": "bool", "default": False}, "purge_data": {"type": "bool", "default": False},
    "confirm_name": {"type": "str"}, "confirm_data_loss": {"type": "bool", "default": False},
    "repair": {"type": "bool", "default": False}, "reconfigure": {"type": "bool", "default": False},
    "keep_cookies": {"type": "list", "elements": "str"},
    "vhosts": {"type": "dict", "options": {"domain": {"type": "str"}, "opac_port": {"type": "int"}, "opac_prefix": {"type": "str"}, "opac_suffix": {"type": "str"}, "staff_port": {"type": "int"}, "staff_prefix": {"type": "str"}, "staff_suffix": {"type": "str"}}},
    "db_request_path": {"type": "path"}, "koha_create_path": {"type": "path"}, "koha_remove_path": {"type": "path"},
}


def _safe_fingerprint(p):
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k not in ("password", "db_credentials")}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value
    persistent = {k: v for k, v in p.items() if k not in ("confirm_name", "confirm_data_loss", "repair", "reconfigure", "remove_database", "purge_data")}
    return hashlib.sha256(json.dumps(clean(persistent), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _find_binary(explicit):
    candidates = [explicit] if explicit else ["/usr/sbin/koha-create", "/usr/bin/koha-create"]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("koha-create") if not explicit else None


def _write_private(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(content)
    os.chmod(path, 0o600)


def _existing_db_credentials(config_path, name):
    """Read DB fields from an existing Koha config without exposing them."""
    root = ET.parse(config_path).getroot()
    def value(tag):
        node = root.find(".//yazgfs/config/" + tag)
        return (node.text or "").strip() if node is not None else ""
    username, password = value("user"), value("pass")
    database = value("database")
    host = value("hostname") or "localhost"
    if (not all((username, password, database)) or any("\n" in x or ":" in x for x in (username, password, database, host))
            or not re.fullmatch(r"[A-Za-z0-9_]{1,32}", username)
            or not db_password_is_safe(password)
            or not re.fullmatch(r"[A-Za-z0-9_]{1,64}", database)
            or not re.fullmatch(r"[A-Za-z0-9_.:\[\]-]+", host)):
        raise ModuleInputError("no se pudieron recuperar credenciales DB seguras del koha-conf.xml; proporcione db_credentials/passwdfile")
    return "%s:%s:%s:%s:%s\n" % (name, username, password, database, host)


def _read_passwd_record(path, name):
    """Read and validate only the requested passwdfile row; never report contents."""
    try:
        with open(path, encoding="utf-8") as stream:
            rows = [line.rstrip("\r\n").split(":") for line in stream if line.startswith(name + ":")]
    except OSError as exc:
        raise ModuleInputError("no se pudo leer passwdfile (%s)" % exc.__class__.__name__)
    if len(rows) != 1 or len(rows[0]) != 5:
        raise ModuleInputError("passwdfile debe tener exactamente una fila Koha para name con cinco campos")
    instance, username, password, database, host = rows[0]
    if (instance != name or not re.fullmatch(r"[A-Za-z0-9_]{1,32}", username)
            or not db_password_is_safe(password)
            or not re.fullmatch(r"[A-Za-z0-9_]{1,64}", database)
            or not re.fullmatch(r"[A-Za-z0-9_.:\[\]-]+", host)):
        raise ModuleInputError("passwdfile contiene valores no soportados de forma segura por koha-create")
    return rows[0]


def _check_letsencrypt(module):
    if not shutil.which("letsencrypt"):
        raise ModuleInputError("letsencrypt=true requiere el ejecutable letsencrypt; instale/configure el cliente antes de ejecutar el módulo")
    rc, out, err = module.run_command(["dpkg-query", "-W", "-f=${Status}", "letsencrypt"], check_rc=False)
    if rc or "install ok installed" not in out:
        raise ModuleInputError("letsencrypt=true requiere que el paquete Debian letsencrypt ya esté instalado; el módulo no instala paquetes ni acepta prompts")
    apache = "/usr/sbin/apachectl" if os.path.exists("/usr/sbin/apachectl") else "/usr/sbin/apache2ctl"
    rc, out, err = module.run_command([apache, "-M"], check_rc=False)
    if rc or "ssl_module" not in out:
        raise ModuleInputError("letsencrypt=true requiere mod_ssl habilitado en Apache (a2enmod ssl)")


def _check_apache_prerequisites(module):
    """Fail before koha-create mutates the host if Koha's Apache modules are absent."""
    apache = "/usr/sbin/apachectl" if os.path.exists("/usr/sbin/apachectl") else "/usr/sbin/apache2ctl"
    rc, out, err = module.run_command([apache, "-M"], check_rc=False)
    modules = out + err
    if rc:
        raise ModuleInputError("no se pudo comprobar Apache antes de crear la instancia; revise apachectl -M y su configuración")
    if "mpm_itk_module" not in modules:
        raise ModuleInputError("Koha requiere mpm_itk habilitado en Apache; instale libapache2-mpm-itk y ejecute a2enmod mpm_itk")
    if "rewrite_module" not in modules:
        raise ModuleInputError("Koha requiere mod_rewrite habilitado en Apache; ejecute a2enmod rewrite y recargue Apache")
    if "cgi_module" not in modules:
        raise ModuleInputError("Koha requiere mod_cgi habilitado en Apache; ejecute a2enmod cgi y recargue Apache")


def _safe_backend_failure_hint(output):
    """Map common backend errors to fixed, non-sensitive diagnostics."""
    if re.search(r"mpm_itk", output, re.IGNORECASE):
        return "Koha requiere mpm_itk habilitado en Apache."
    if re.search(r"mod_rewrite|rewrite_module", output, re.IGNORECASE):
        return "Koha requiere mod_rewrite habilitado en Apache."
    if re.search(r"mod_cgi|cgi_module", output, re.IGNORECASE):
        return "Koha requiere mod_cgi habilitado en Apache."
    if re.search(r"ERROR\s+1045|access denied", output, re.IGNORECASE):
        return "MariaDB rechazó la autenticación; revise su configuración local sin compartir credenciales."
    if re.search(r"ERROR\s+1044|command denied", output, re.IGNORECASE):
        return "MariaDB rechazó los privilegios requeridos para crear la base de datos."
    if re.search(r"ERROR\s+1007|database exists", output, re.IGNORECASE):
        return "La base de datos convencional ya existe; inspecciónela antes de continuar."
    if re.search(r"ERROR\s+2002|ERROR\s+2003|can't connect to.*server", output, re.IGNORECASE):
        return "No se pudo conectar con MariaDB; revise que el servicio esté activo."
    if re.search(r"can't locate .*\.pm|module .* not found", output, re.IGNORECASE):
        return "Falta una dependencia Perl de Koha en el host."
    if re.search(r"command not found|no such file or directory", output, re.IGNORECASE):
        return "Falta un ejecutable o archivo requerido por Koha."
    if re.search(r"permission denied|operation not permitted", output, re.IGNORECASE):
        return "Koha encontró un problema de permisos en el host."
    return "Revise los servicios y dependencias del host; la salida del backend se omitió por seguridad."


def main():
    module = AnsibleModule(argument_spec=ARGUMENT_SPEC, supports_check_mode=True)
    p = module.params
    name = p["name"]
    mode = p["db_mode"]
    config_path = "/etc/koha/sites/%s/koha-conf.xml" % name
    apache_path = "/etc/apache2/sites-available/%s.conf" % name
    state_dir = "/var/lib/koha/%s" % name
    marker_path = os.path.join(state_dir, ".ansible-koha-instance-state")
    request_path = p.get("db_request_path") or os.path.join(state_dir, "%s-db-request.txt" % name)
    try:
        validate_params(p)
        if p.get("vhosts"):
            v = p["vhosts"]
            if "domain" not in v or not re.fullmatch(r"\.?[A-Za-z0-9.-]+", v["domain"]):
                raise ModuleInputError("vhosts.domain es obligatorio y solo admite sufijo DNS opcional con punto inicial")
            for key in ("opac_prefix", "opac_suffix", "staff_prefix", "staff_suffix"):
                if v.get(key) and not re.fullmatch(r"[A-Za-z0-9-]*", v[key]):
                    raise ModuleInputError("vhosts.%s solo admite caracteres DNS seguros" % key)
            for key in ("opac_port", "staff_port"):
                if v.get(key) is not None and not 1 <= v[key] <= 65535:
                    raise ModuleInputError("vhosts.%s debe estar entre 1 y 65535" % key)
        if p.get("keep_cookies") and not all(re.fullmatch(r"[A-Za-z0-9_-]+", x) for x in p["keep_cookies"]):
            raise ModuleInputError("keep_cookies solo admite nombres de cookie alfanuméricos, _ y -")
        if p.get("db_credentials"):
            creds = p["db_credentials"]
            if not creds["username"] or not creds["password"] or any(c in creds["username"] + creds["password"] for c in ":\r\n"):
                raise ModuleInputError("db_credentials requiere username/password sin dos puntos ni saltos de línea (formato passwdfile Koha)")
            if not re.fullmatch(r"[A-Za-z0-9_]{1,32}", creds["username"]) or not db_password_is_safe(creds["password"]):
                raise ModuleInputError("db_credentials requiere username [A-Za-z0-9_]{1,32}; password de 1-128 caracteres ASCII imprimibles sin espacios. Por seguridad de koha-create no se admiten : ' & / \\ < >")
        if mode == "request" and os.path.exists(request_path):
            raise ModuleInputError("db_request_path ya existe; se conserva para no sobrescribir una solicitud con credenciales")
        if mode == "populate" and not p.get("db_request_path"):
            try:
                with open(marker_path, encoding="utf-8") as f:
                    prior_marker = json.load(f)
                request_path = prior_marker.get("request_file", request_path)
            except (OSError, ValueError):
                pass
        detected, paths, marker = inspect_state(name, marker_path, request_path)
        rebuild = False
        if p["state"] == "absent":
            if detected == "absent":
                module.exit_json(changed=False, name=name, state="absent", actions=[], notices=["No quedan archivos de instancia activos; los datos residuales de /var/lib/koha se conservan."] if paths.get("site_dir") else [])
            if p.get("confirm_name") != name or not p.get("confirm_data_loss"):
                raise ModuleInputError("state=absent elimina archivos y servicios; confirme con confirm_name=name y confirm_data_loss=true")
            if module.check_mode:
                module.exit_json(changed=True, name=name, state="absent", actions=["ejecutar koha-remove"], notices=["Plan previsto; preserve DB por defecto. remove_database/purge_data amplían el borrado."])
            if os.geteuid() != 0:
                raise ModuleInputError("koha-remove requiere root; ejecute la tarea con become: true")
            remove_binary = p.get("koha_remove_path") or shutil.which("koha-remove")
            if not remove_binary:
                raise ModuleInputError("no se encontró koha-remove; instale los paquetes Koha o defina koha_remove_path")
            if not os.path.isdir("/etc/koha/sites/%s" % name):
                raise ModuleInputError("koha-remove requiere /etc/koha/sites/%s; el estado parcial no contiene el directorio de sitio" % name)
            remove_argv = [remove_binary]
            if not p.get("remove_database"):
                remove_argv.append("--keep-mysql")
            if p.get("purge_data"):
                remove_argv.append("--purge-all")
            remove_argv.append(name)
            rc, out, err = module.run_command(remove_argv, check_rc=False)
            if rc:
                raise ModuleInputError("koha-remove falló (rc=%s); stdout/stderr se omitieron por seguridad" % rc)
            if os.path.exists(marker_path):
                os.unlink(marker_path)
            warnings = []
            if not p.get("remove_database"):
                warnings.append("La base de datos se conservó.")
            elif p.get("database") and p["database"] != "koha_%s" % name:
                warnings.append("koha-remove elimina su DB convencional koha_<name>; revise manualmente la DB personalizada %s." % p["database"])
            if not p.get("purge_data"):
                warnings.append("/var/lib/koha y uploads se conservaron; use purge_data=true si desea borrarlos.")
            module.exit_json(changed=True, name=name, state="absent", actions=["koha-remove"], notices=warnings)
        if mode == "populate":
            if detected != "requested":
                raise ModuleInputError("populate requiere estado requested coherente (config Koha, Apache, directorio y marcador de solicitud); estado detectado: %s" % detected)
        elif detected == "requested":
            raise ModuleInputError("la instancia está requested; use db_mode=populate tras preparar la base externa")
        elif detected == "present":
            if p.get("repair"):
                raise ModuleInputError("repair solo se aplica al estado partial; use reconfigure=true para cambiar configuración present")
            try:
                with open(marker_path, encoding="utf-8") as f:
                    saved = json.load(f)
            except Exception:
                raise ModuleInputError("marcador de instancia ilegible; inspeccione manualmente, no se ejecutará koha-create")
            changed_config = saved.get("fingerprint") != _safe_fingerprint(p)
            if changed_config and not p.get("reconfigure"):
                raise ModuleInputError("la instancia existe con parámetros distintos (drift); use reconfigure=true junto con las dos confirmaciones para reconstruir su configuración preservando la DB")
            if not changed_config:
                module.exit_json(changed=False, name=name, state="present", db_mode=mode, config_path=config_path, apache_site_path=apache_path, actions=[], notices=["La instancia está creada; koha-create no se ejecutó."])
            rebuild = True
        elif detected == "partial":
            if not p.get("repair"):
                raise ModuleInputError("recursos parciales o instancia no administrada detectados (%s); use repair=true y las dos confirmaciones para reconstruir la configuración preservando la DB" % ", ".join(k for k, exists in paths.items() if exists))
            rebuild = True
        elif p.get("repair") or p.get("reconfigure"):
            raise ModuleInputError("repair requiere state partial y reconfigure requiere una instancia present")

        binary = _find_binary(p.get("koha_create_path"))
        if not binary:
            raise ModuleInputError("no se encontró koha-create; instale los paquetes Koha o defina koha_create_path")
        if os.geteuid() != 0:
            raise ModuleInputError("koha-create requiere root; ejecute la tarea con become: true")
        if p.get("configfile") and not os.path.isfile(p["configfile"]):
            raise ModuleInputError("configfile no existe en el nodo remoto")
        if p.get("passwdfile") and not os.path.isfile(p["passwdfile"]):
            raise ModuleInputError("passwdfile no existe en el nodo remoto")
        supplied_db_record = _read_passwd_record(p["passwdfile"], name) if p.get("passwdfile") else None
        if p.get("letsencrypt") and p.get("tls_termination") == "proxy":
            raise ModuleInputError("Let's Encrypt de koha-create configura TLS en Apache; no lo use cuando HAProxy/proxy termina TLS")
        if module.check_mode:
            planned = ["koha-remove --keep-mysql", "koha-create --use-db"] if rebuild else ["ejecutar koha-create en modo %s" % mode]
            module.exit_json(changed=True, name=name, state="requested" if mode == "request" else "present", db_mode="use" if rebuild else mode,
                             config_path=config_path, apache_site_path=apache_path,
                             actions=planned, notices=["Plan previsto; no se verificó que Apache/DB permitan completar la operación."])
        _check_apache_prerequisites(module)
        if p.get("letsencrypt"):
            _check_letsencrypt(module)

        # Check help before writing files or invoking the mutating command. The
        # module sends no help output to Ansible because output can vary by version.
        help_rc, help_out, help_err = module.run_command([binary, "--help"], check_rc=False)
        help_text = help_out + help_err
        backend_mode = "use" if rebuild else mode
        needed = ["--configfile", {"create": "--create-db", "request": "--request-db", "populate": "--populate-db", "use": "--use-db"}[backend_mode]]
        option_flags = {
            "marcflavor": "--marcflavor", "zebralang": "--zebralang", "elasticsearch_server": "--elasticsearch-server",
            "memcached_servers": "--memcached-servers", "memcached_prefix": "--memcached-prefix", "enable_sru": "--enable-sru",
            "sru_port": "--sru-port", "dbhost": "--dbhost", "database": "--database", "passwdfile": "--passwdfile",
            "defaultsql": "--defaultsql", "adminuser": "--adminuser", "template_cache_dir": "--template-cache-dir",
            "timezone": "--timezone", "upload_path": "--upload-path", "tmp_path": "--tmp-path", "keep_cookies": "--keep-cookie",
        }
        for key, flag in option_flags.items():
            if p.get(key):
                needed.append(flag)
        if p.get("smtp"):
            needed.extend("--smtp-%s" % key.replace("ssl_mode", "ssl-mode").replace("username", "user-name") for key, value in p["smtp"].items() if value is not None)
        if p.get("message_broker"):
            needed.extend("--mb-%s" % key.replace("username", "user").replace("password", "pass") for key, value in p["message_broker"].items() if value is not None)
        if p.get("letsencrypt"):
            needed.append("--letsencrypt")
        if rebuild:
            needed.append("--passwdfile")
        missing = [flag for flag in needed if flag not in help_text]
        if missing:
            raise ModuleInputError("koha-create instalado no anuncia opciones requeridas (%s); compatibilidad no verificada" % ", ".join(missing))

        tmpdir = tempfile.mkdtemp(prefix="ansible-koha-create-")
        os.chmod(tmpdir, 0o700)
        try:
            cfg = os.path.join(tmpdir, "koha-create.conf")
            passwdfile = None
            existing_db_record = None
            if rebuild and os.path.isfile(config_path):
                existing_db_record = _existing_db_credentials(config_path, name).strip().split(":")
                if p.get("database") and p["database"] != existing_db_record[3]:
                    raise ModuleInputError("reconfigure no cambia de base de datos; database debe coincidir con la instancia actual")
                if p.get("dbhost") and p["dbhost"] != existing_db_record[4]:
                    raise ModuleInputError("reconfigure no migra bases de datos; dbhost debe coincidir con la instancia actual")
            if p.get("db_credentials"):
                passwdfile = os.path.join(tmpdir, "passwd")
                if rebuild and not existing_db_record and not p.get("database"):
                    raise ModuleInputError("repair sin koha-conf.xml requiere database para identificar la DB que se conservará")
                dbname = existing_db_record[3] if existing_db_record else (p.get("database") or "koha_%s" % name)
                dbhost = existing_db_record[4] if existing_db_record else (p.get("dbhost") or "localhost")
                username = p["db_credentials"]["username"]
                password = p["db_credentials"]["password"]
                _write_private(passwdfile, "%s:%s:%s:%s:%s\n" % (name, username, password, dbname, dbhost))
            elif rebuild and p.get("passwdfile"):
                if existing_db_record and (supplied_db_record[3], supplied_db_record[4]) != (existing_db_record[3], existing_db_record[4]):
                    raise ModuleInputError("passwdfile apunta a una DB/host distintos; repair/reconfigure preserva la DB actual")
                passwdfile = p["passwdfile"]
            elif rebuild and os.path.isfile(config_path):
                passwdfile = os.path.join(tmpdir, "passwd")
                _write_private(passwdfile, ":".join(existing_db_record) + "\n")
            elif rebuild:
                raise ModuleInputError("para reparar/reconfigurar sin koha-conf.xml debe proporcionar db_credentials o passwdfile")
            if rebuild and not os.path.isdir("/etc/koha/sites/%s" % name):
                raise ModuleInputError("la reconstrucción requiere el directorio /etc/koha/sites/%s; no se eliminará parcialmente el resto del sistema" % name)
            _write_private(cfg, render_config(p, passwdfile))
            if rebuild:
                if p.get("defaultsql"):
                    raise ModuleInputError("defaultsql no se aplica en repair/reconfigure porque el backend se ejecuta con --use-db")
                if not p.get("db_credentials") and not p.get("passwdfile") and not os.path.isfile(config_path):
                    raise ModuleInputError("repair/reconfigure sin configfile requiere credenciales DB explícitas")
                remove_binary = p.get("koha_remove_path") or shutil.which("koha-remove")
                if not remove_binary:
                    raise ModuleInputError("repair/reconfigure requiere koha-remove; defina koha_remove_path si no está en PATH")
                rc, out, err = module.run_command([remove_binary, "--keep-mysql", name], check_rc=False)
                if rc:
                    raise ModuleInputError("koha-remove --keep-mysql falló (rc=%s); stdout/stderr se omitieron por seguridad" % rc)
                if os.path.exists(marker_path):
                    os.unlink(marker_path)
            argv = build_argv(binary, backend_mode, cfg, name)
            if mode == "request" and not rebuild:
                if not os.path.isdir(os.path.dirname(request_path)):
                    raise ModuleInputError("el directorio padre de db_request_path debe existir")
                # koha-create writes NAME-db-request.txt to cwd; private cwd
                # prevents accidental exposure while it is being generated.
                rc, out, err = module.run_command(argv, cwd=tmpdir, check_rc=False)
                generated = os.path.join(tmpdir, "%s-db-request.txt" % name)
                if rc == 0 and os.path.isfile(generated):
                    os.replace(generated, request_path)
                    os.chmod(request_path, 0o600)
            else:
                rc, out, err = module.run_command(argv, cwd=tmpdir, check_rc=False)
            if rc != 0:
                hint = _safe_backend_failure_hint(out + "\n" + err)
                raise ModuleInputError("koha-create falló (rc=%s). %s" % (rc, hint))
            final_state = "requested" if mode == "request" and not rebuild else "present"
            # Only mark success if the expected resource set really appeared.
            after, after_paths, _ = inspect_state(name, marker_path, request_path)
            required_resources = ("config", "apache", "site_dir", "user", "group")
            if not all(after_paths.get(key, False) for key in required_resources):
                raise ModuleInputError("koha-create terminó sin error pero faltan recursos esperados (%s); estado parcial, no se reintentará automáticamente" % ", ".join(k for k in required_resources if not after_paths.get(k, False)))
            _write_private(marker_path, json.dumps({"state": final_state, "fingerprint": _safe_fingerprint(p), "request_file": request_path if mode == "request" else None}, sort_keys=True) + "\n")
            # Marker is stored in a Koha-owned directory, private to root.
            os.chmod(marker_path, 0o600)
            result = {"changed": True, "name": name, "state": final_state, "db_mode": mode, "config_path": config_path, "apache_site_path": apache_path,
                      "actions": ["koha-create --%s" % mode], "notices": []}
            if mode == "request" and not rebuild:
                result["request_file"] = request_path
            if p.get("vhosts"):
                v = p["vhosts"]
                domain = v["domain"].lstrip(".")
                result["opac_hostname"] = "%s%s%s.%s" % (v.get("opac_prefix", ""), name, v.get("opac_suffix", ""), domain)
                result["staff_hostname"] = "%s%s%s.%s" % (v.get("staff_prefix", ""), name, v.get("staff_suffix", ""), domain)
            if rebuild:
                result["db_mode"] = "use"
                result["actions"] = ["koha-remove --keep-mysql", "koha-create --use-db"]
                result["notices"] = ["Se reconstruyeron configuración y servicios; DB y /var/lib/koha se conservaron."]
            if p.get("letsencrypt"):
                result["notices"].append("Let's Encrypt local modifica Apache y solicita certificados; los DNS deben resolver públicamente y el puerto 80 debe llegar a este host.")
            module.exit_json(**result)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except ModuleInputError as exc:
        module.fail_json(msg=str(exc), name=name, state="unknown", db_mode=mode)
    except OSError as exc:
        module.fail_json(msg="error de filesystem ejecutando la operación Koha (%s); se omitieron datos sensibles" % exc.__class__.__name__, name=name, state="unknown", db_mode=mode)


if __name__ == "__main__":
    main()
