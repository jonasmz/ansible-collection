#!/usr/bin/python
# SPDX-License-Identifier: MIT-0
"""Create Koha instances using the packaged koha-create command."""

DOCUMENTATION = r'''
---
module: instance
short_description: Crea de forma declarativa una instancia Koha
description:
  - Ejecuta koha-create solo cuando la instancia está ausente o en etapa request.
  - Registra un marcador propio al terminar; una instancia completa sin marcador solo se administra con I(adopt) o I(repair).
  - Usa un archivo configfile temporal privado para evitar el límite de argumentos y proteger secretos de RabbitMQ.
  - La compatibilidad de opciones depende de la versión instalada de koha-create.
version_added: "1.0.0"
author: Jonas MZ
options:
  instance:
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
    description: Mapea --template-cache-dir; default nativo /var/cache/koha/<instance>/templates.
    type: path
  timezone:
    description: Mapea --timezone. Las tablas de zonas horarias de MariaDB no se cargan aquí; use M(jmz.koha.mariadb_timezone) antes de crear la instancia.
    type: str
  upload_path:
    description: Mapea --upload-path; default nativo /var/lib/koha/<instance>/uploads.
    type: path
  tmp_path:
    description: Mapea --tmp-path; default nativo /var/lib/koha/<instance>/tmp.
    type: path
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
    description: Con state=absent permite borrar la DB koha_<instance>; por defecto se conserva.
    type: bool
    default: false
  purge_data:
    description: Con state=absent elimina /var/lib/koha/<name> y spool mediante --purge-all.
    type: bool
    default: false
  confirm_instance:
    description: Debe repetir instance exactamente para operaciones destructivas.
    type: str
  confirm_data_loss:
    description: Segunda confirmacion explicita requerida para operaciones destructivas.
    type: bool
    default: false
  adopt:
    description:
      - Registra el marcador de una instancia Koha completa que no lo tiene (creada a mano o por otra herramienta), sin modificarla.
      - No verifica que su configuración real coincida con los parámetros; estos pasan a ser la referencia para detectar drift.
      - No hace nada si la instancia ya está administrada y falla si está incompleta.
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
    instance: biblioteca
    db_mode: create
    marcflavor: marc21
    zebralang: es
  become: true

- name: Crear detrás de HAProxy
  jmz.koha.instance:
    instance: biblioteca
    db_mode: create
    vhosts:
      domain: .example.org
      opac_port: 80
      staff_port: 80
      staff_suffix: -admin
    memcached_enabled: true
  become: true
  no_log: true

- name: Usar DB existente
  jmz.koha.instance:
    instance: biblioteca
    db_mode: use
    database: koha_biblioteca
    db_credentials:
      username: koha_biblioteca
      password: "{{ vault_koha_db_password }}"
  become: true
  no_log: true

- name: Solicitar DB externa
  jmz.koha.instance:
    instance: biblioteca
    db_mode: request
    db_request_path: /root/koha-db-requests/biblioteca-db-request.txt
  become: true
  no_log: true

- name: Completar solicitud previa
  jmz.koha.instance:
    instance: biblioteca
    db_mode: populate
  become: true
  no_log: true

- name: Reconfigurar una instancia preservando la DB
  jmz.koha.instance:
    instance: biblioteca
    reconfigure: true
    confirm_instance: biblioteca
    confirm_data_loss: true
    vhosts:
      domain: .example.org
      staff_suffix: -admin
  become: true

- name: Retirar instancia, preservando DB y datos
  jmz.koha.instance:
    instance: biblioteca
    state: absent
    confirm_instance: biblioteca
    confirm_data_loss: true
  become: true

- name: Crear con TLS terminado localmente
  jmz.koha.instance:
    instance: biblioteca
    db_mode: create
    vhosts:
      domain: .example.org
    letsencrypt: true
    tls_termination: local
  become: true
'''

RETURN = r'''
instance: {description: Nombre de instancia validado, returned: always, type: str}
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

import os
import shutil
import tempfile

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import (
    ModuleInputError, build_argv, choice_normalizer, render_config, validate_params,
)
from ansible_collections.jmz.koha.plugins.module_utils.koha_instance_backend import (
    backup_instance, check_apache_prerequisites, check_letsencrypt, existing_db_credentials, failure_hint,
    read_passwd_record, require_options, resolve_binary, restore_site_config, vhost_hostnames, write_private, BACKUP_ROOT,
)
from ansible_collections.jmz.koha.plugins.module_utils.koha_instance_state import (
    fingerprint, inspect_state, instance_lock, remove_marker, write_marker,
)


DB_MODES = ["create", "request", "populate", "use"]
ARGUMENT_SPEC = {
    "instance": {"type": "str", "required": True}, "state": {"type": choice_normalizer(["present", "absent"]), "default": "present", "choices": ["present", "absent"]},
    "db_mode": {"type": choice_normalizer(DB_MODES), "default": "create", "choices": DB_MODES},
    "marcflavor": {"type": choice_normalizer(["marc21", "unimarc"]), "choices": ["marc21", "unimarc"]},
    "zebralang": {"type": choice_normalizer(["cs", "el", "en", "es", "fr", "nb", "ru", "uk"]), "choices": ["cs", "el", "en", "es", "fr", "nb", "ru", "uk"]},
    "elasticsearch_server": {"type": "str"}, "memcached_servers": {"type": "list", "elements": "str"},
    "memcached_prefix": {"type": "str"}, "memcached_enabled": {"type": "bool"}, "enable_sru": {"type": "bool", "default": False},
    "sru_port": {"type": "int"}, "dbhost": {"type": "str"}, "database": {"type": "str"},
    "passwdfile": {"type": "path"}, "defaultsql": {"type": "path"}, "adminuser": {"type": "int"},
    "configfile": {"type": "path"}, "template_cache_dir": {"type": "path"}, "timezone": {"type": "str"},
    "upload_path": {"type": "path"}, "tmp_path": {"type": "path"},
    "message_broker": {"type": "dict", "no_log": True, "options": {
        "host": {"type": "str"}, "port": {"type": "int"}, "username": {"type": "str"},
        "password": {"type": "str", "no_log": True}, "vhost": {"type": "str"}}},
    "db_credentials": {"type": "dict", "no_log": True, "options": {"username": {"type": "str", "required": True}, "password": {"type": "str", "required": True, "no_log": True}}},
    "letsencrypt": {"type": "bool", "default": False}, "tls_termination": {"type": choice_normalizer(["local", "proxy"]), "choices": ["local", "proxy"]},
    "remove_database": {"type": "bool", "default": False}, "purge_data": {"type": "bool", "default": False},
    "confirm_instance": {"type": "str"}, "confirm_data_loss": {"type": "bool", "default": False},
    "adopt": {"type": "bool", "default": False}, "repair": {"type": "bool", "default": False}, "reconfigure": {"type": "bool", "default": False},
    "keep_cookies": {"type": "list", "elements": "str"},
    "vhosts": {"type": "dict", "options": {"domain": {"type": "str"}, "opac_port": {"type": "int"}, "opac_prefix": {"type": "str"}, "opac_suffix": {"type": "str"}, "staff_port": {"type": "int"}, "staff_prefix": {"type": "str"}, "staff_suffix": {"type": "str"}}},
    "db_request_path": {"type": "path"}, "koha_create_path": {"type": "path"}, "koha_remove_path": {"type": "path"},
}
REBUILD_ACTIONS = ["koha-remove --keep-mysql", "koha-create --use-db"]


def plan_action(p, detected, marker):
    """Decide the single operation to run: noop, adopt, remove, rebuild or a db_mode.

    Pure function of the parameters and the inspected state, shared by check
    mode and real runs so both always agree.
    """
    mode = p["db_mode"]
    if p["state"] == "absent":
        if detected == "absent":
            return "noop"
        if p.get("confirm_instance") != p["instance"] or not p.get("confirm_data_loss"):
            raise ModuleInputError("state=absent elimina archivos y servicios; confirme con confirm_instance=instance y confirm_data_loss=true")
        return "remove"
    if p["adopt"]:
        if detected == "present":
            return "noop"
        if detected == "unmanaged":
            return "adopt"
        raise ModuleInputError("adopt requiere una instancia completa sin marcador; estado detectado: %s" % detected)
    if mode == "populate":
        if detected != "requested":
            raise ModuleInputError("populate requiere estado requested coherente (config Koha, Apache, directorio y marcador de solicitud); estado detectado: %s" % detected)
    elif detected == "requested":
        raise ModuleInputError("la instancia está requested; use db_mode=populate tras preparar la base externa")
    if detected == "present":
        if p["repair"]:
            raise ModuleInputError("repair solo se aplica a instancias incompletas o no administradas; use reconfigure=true para cambiar configuración present")
        if marker.get("fingerprint") == fingerprint(p):
            return "noop"
        if not p["reconfigure"]:
            raise ModuleInputError("la instancia existe con parámetros distintos (drift); use reconfigure=true junto con las dos confirmaciones para reconstruir su configuración preservando la DB")
        return "rebuild"
    if detected in ("partial", "unmanaged"):
        if p["repair"]:
            return "rebuild"
        if detected == "unmanaged":
            raise ModuleInputError("la instancia está completa pero no la administra este módulo (sin marcador); use adopt=true para registrarla sin modificarla, o repair=true y las dos confirmaciones para reconstruirla")
        raise ModuleInputError("recursos parciales detectados; use repair=true y las dos confirmaciones para reconstruir la configuración preservando la DB")
    if p["repair"] or p["reconfigure"]:
        raise ModuleInputError("repair requiere una instancia incompleta o no administrada y reconfigure requiere una instancia present")
    return mode


class Context:
    """Paths and identifiers of one instance."""

    def __init__(self, p):
        self.name = p["instance"]
        self.config_path = "/etc/koha/sites/%s/koha-conf.xml" % self.name
        self.apache_path = "/etc/apache2/sites-available/%s.conf" % self.name
        self.state_dir = "/var/lib/koha/%s" % self.name
        self.marker_path = os.path.join(self.state_dir, ".ansible-koha-instance-state")
        self.request_path = p.get("db_request_path") or os.path.join(self.state_dir, "%s-db-request.txt" % self.name)


def _result(ctx, p, action, state, actions, notices, changed=True):
    result = {"changed": changed, "instance": ctx.name, "state": state, "db_mode": p["db_mode"],
              "config_path": ctx.config_path, "apache_site_path": ctx.apache_path,
              "actions": actions, "notices": notices}
    if p.get("vhosts") and state != "absent":
        result["opac_hostname"], result["staff_hostname"] = vhost_hostnames(ctx.name, p["vhosts"])
    if action == "request":
        result["request_file"] = ctx.request_path
    return result


def _plan_result(ctx, p, action, detected):
    if action == "noop":
        if p["state"] == "absent":
            return _result(ctx, p, action, "absent", [], [], changed=False)
        return _result(ctx, p, action, detected, [], ["La instancia está creada; koha-create no se ejecutó."], changed=False)
    if action == "remove":
        return _result(ctx, p, action, "absent", ["ejecutar koha-remove"],
                       ["Plan previsto; preserve DB por defecto. remove_database/purge_data amplían el borrado."])
    if action == "adopt":
        return _result(ctx, p, action, "present", ["registrar marcador de instancia"],
                       ["La instancia no se modifica; solo se registra su marcador."])
    if action == "rebuild":
        result = _result(ctx, p, action, "present", list(REBUILD_ACTIONS),
                         ["Plan previsto; no se verificó que Apache/DB permitan completar la operación."])
        result["db_mode"] = "use"
        return result
    return _result(ctx, p, action, "requested" if action == "request" else "present",
                   ["ejecutar koha-create en modo %s" % action],
                   ["Plan previsto; no se verificó que Apache/DB permitan completar la operación."])


def _require_root(what):
    if os.geteuid() != 0:
        raise ModuleInputError("%s requiere root; ejecute la tarea con become: true" % what)


def _apply_remove(module, p, ctx, actions):
    remove_binary = resolve_binary(module, p.get("koha_remove_path"), "koha-remove")
    site_dir = "/etc/koha/sites/%s" % ctx.name
    if not os.path.isdir(site_dir):
        # koha-remove aborts without this directory, which would leave the user, Apache site
        # and services of a partial instance behind. It deletes the directory again when empty.
        os.mkdir(site_dir, 0o755)
        actions.append("crear directorio de sitio vacío para koha-remove")
    argv = [remove_binary] + ([] if p["remove_database"] else ["--keep-mysql"]) + (["--purge-all"] if p["purge_data"] else []) + [ctx.name]
    rc, _, _ = module.run_command(argv, check_rc=False)
    if rc:
        raise ModuleInputError("koha-remove falló (rc=%s); stdout/stderr se omitieron por seguridad" % rc)
    actions.append("koha-remove")
    remove_marker(ctx.marker_path)
    notices = []
    if not p["remove_database"]:
        notices.append("La base de datos se conservó.")
    elif p.get("database") and p["database"] != "koha_%s" % ctx.name:
        notices.append("koha-remove elimina su DB convencional koha_<instance>; revise manualmente la DB personalizada %s." % p["database"])
    if not p["purge_data"]:
        notices.append("/var/lib/koha y uploads se conservaron; use purge_data=true si desea borrarlos.")
    return _result(ctx, p, "remove", "absent", actions, notices)


def _apply_adopt(p, ctx, actions):
    write_marker(ctx.marker_path, "present", fingerprint(p))
    actions.append("registrar marcador de instancia")
    return _result(ctx, p, "adopt", "present", actions, ["La instancia no se modificó; se registró su marcador."])


def _prepare_passwdfile(p, ctx, tmpdir, rebuild):
    """Resolve the passwdfile koha-create receives and validate it against the live instance."""
    existing = None
    if rebuild and os.path.isfile(ctx.config_path):
        existing = existing_db_credentials(ctx.config_path, ctx.name, p.get("db_credentials")).strip().split(":")
        if p.get("database") and p["database"] != existing[3]:
            raise ModuleInputError("reconfigure no cambia de base de datos; database debe coincidir con la instancia actual")
        if p.get("dbhost") and p["dbhost"] != existing[4]:
            raise ModuleInputError("reconfigure no migra bases de datos; dbhost debe coincidir con la instancia actual")
    supplied = read_passwd_record(p["passwdfile"], ctx.name) if p.get("passwdfile") else None
    if p.get("db_credentials"):
        if rebuild and not existing and not p.get("database"):
            raise ModuleInputError("repair sin koha-conf.xml requiere database para identificar la DB que se conservará")
        passwdfile = os.path.join(tmpdir, "passwd")
        record = [ctx.name, p["db_credentials"]["username"], p["db_credentials"]["password"],
                  existing[3] if existing else (p.get("database") or "koha_%s" % ctx.name),
                  existing[4] if existing else (p.get("dbhost") or "localhost")]
        write_private(passwdfile, ":".join(record) + "\n")
        return passwdfile
    if rebuild and p.get("passwdfile"):
        if existing and (supplied[3], supplied[4]) != (existing[3], existing[4]):
            raise ModuleInputError("passwdfile apunta a una DB/host distintos; repair/reconfigure preserva la DB actual")
        return p["passwdfile"]
    if rebuild and existing:
        passwdfile = os.path.join(tmpdir, "passwd")
        write_private(passwdfile, ":".join(existing) + "\n")
        return passwdfile
    if rebuild:
        raise ModuleInputError("para reparar/reconfigurar sin koha-conf.xml debe proporcionar db_credentials o passwdfile")
    return None


def _apply_build(module, p, ctx, action, actions):
    """Run koha-create for create/request/populate/use, or koha-remove + koha-create for a rebuild."""
    rebuild = action == "rebuild"
    mode = p["db_mode"]
    backend_mode = "use" if rebuild else action
    create_binary = resolve_binary(module, p.get("koha_create_path"), "koha-create")
    remove_binary = resolve_binary(module, p.get("koha_remove_path"), "koha-remove") if rebuild else None
    for key in ("configfile", "passwdfile"):
        if p.get(key) and not os.path.isfile(p[key]):
            raise ModuleInputError("%s no existe en el nodo remoto" % key)
    if rebuild and not os.path.isdir("/etc/koha/sites/%s" % ctx.name):
        raise ModuleInputError("la reconstrucción requiere el directorio /etc/koha/sites/%s; no se eliminará parcialmente el resto del sistema" % ctx.name)
    if rebuild and not os.path.isdir(BACKUP_ROOT):
        raise ModuleInputError("la reconstrucción requiere %s para respaldar la configuración actual" % BACKUP_ROOT)
    check_apache_prerequisites(module)
    if p["letsencrypt"]:
        check_letsencrypt(module)
    require_options(module, create_binary, p, backend_mode, rebuild)

    tmpdir = tempfile.mkdtemp(prefix="ansible-koha-create-")
    os.chmod(tmpdir, 0o700)
    backup = None
    try:
        passwdfile = _prepare_passwdfile(p, ctx, tmpdir, rebuild)
        cfg = os.path.join(tmpdir, "koha-create.conf")
        write_private(cfg, render_config(p, passwdfile))
        argv = build_argv(create_binary, backend_mode, cfg, ctx.name)
        if mode == "request" and not rebuild and not os.path.isdir(os.path.dirname(ctx.request_path)):
            raise ModuleInputError("el directorio padre de db_request_path debe existir")
        if rebuild:
            backup = backup_instance(ctx.name)
            rc, _, _ = module.run_command([remove_binary, "--keep-mysql", ctx.name], check_rc=False)
            if rc:
                raise ModuleInputError("koha-remove --keep-mysql falló (rc=%s); stdout/stderr se omitieron por seguridad. Respaldo de la configuración: %s" % (rc, backup))
            actions.append(REBUILD_ACTIONS[0])
            remove_marker(ctx.marker_path)
        # koha-create writes NAME-db-request.txt to cwd; a private cwd keeps it
        # from being exposed while it is being generated.
        rc, out, err = module.run_command(argv, cwd=tmpdir, check_rc=False)
        generated = os.path.join(tmpdir, "%s-db-request.txt" % ctx.name)
        if rc == 0 and action == "request" and os.path.isfile(generated):
            os.replace(generated, ctx.request_path)
            os.chmod(ctx.request_path, 0o600)
        if rc != 0:
            message = "koha-create falló (rc=%s). %s" % (rc, failure_hint(out + "\n" + err))
            if backup:
                restored = restore_site_config(ctx.name, backup)
                actions.append("restaurar configuración previa")
                message += (" La configuración anterior se restauró en /etc/koha/sites/%s (la instancia queda partial: sin usuario ni sitio Apache); "
                            "corrija el problema y repita con repair=true." % ctx.name if restored else
                            " La instancia quedó sin configuración.")
                message += " Respaldo conservado en %s." % backup
            raise ModuleInputError(message)
        actions.append(REBUILD_ACTIONS[1] if rebuild else "koha-create --%s" % action)
        final_state = "requested" if action == "request" else "present"
        # Only mark success if the expected resource set really appeared.
        _, found, _ = inspect_state(ctx.name, ctx.marker_path, ctx.request_path)
        missing = [k for k in ("config", "apache", "site_dir", "user", "group") if not found.get(k)]
        if missing:
            raise ModuleInputError("koha-create terminó sin error pero faltan recursos esperados (%s); estado parcial, no se reintentará automáticamente" % ", ".join(missing))
        write_marker(ctx.marker_path, final_state, fingerprint(p), ctx.request_path if action == "request" else None)
        if backup:
            shutil.rmtree(backup, ignore_errors=True)
        notices = ["Se reconstruyeron configuración y servicios; DB y /var/lib/koha se conservaron."] if rebuild else []
        if p["letsencrypt"]:
            notices.append("Let's Encrypt local modifica Apache y solicita certificados; los DNS deben resolver públicamente y el puerto 80 debe llegar a este host.")
        result = _result(ctx, p, action, final_state, actions, notices)
        if rebuild:
            result["db_mode"] = "use"
        return result
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    module = AnsibleModule(argument_spec=ARGUMENT_SPEC, supports_check_mode=True)
    p = module.params
    name = p["instance"]
    ctx = Context(p)
    actions = []
    try:
        validate_params(p)
        if p["db_mode"] == "request" and os.path.exists(ctx.request_path):
            raise ModuleInputError("db_request_path ya existe; se conserva para no sobrescribir una solicitud con credenciales")
        detected, found, marker = inspect_state(name, ctx.marker_path, ctx.request_path)
        if p["db_mode"] == "populate" and not p.get("db_request_path") and marker.get("request_file"):
            ctx.request_path = marker["request_file"]
            detected, found, marker = inspect_state(name, ctx.marker_path, ctx.request_path)
        action = plan_action(p, detected, marker)
        if module.check_mode or action == "noop":
            module.exit_json(**_plan_result(ctx, p, action, detected))
        _require_root("koha-create/koha-remove")
        with instance_lock(name):
            if action == "remove":
                result = _apply_remove(module, p, ctx, actions)
            elif action == "adopt":
                result = _apply_adopt(p, ctx, actions)
            else:
                result = _apply_build(module, p, ctx, action, actions)
        module.exit_json(**result)
    except (ModuleInputError, OSError) as exc:
        message = str(exc) if isinstance(exc, ModuleInputError) else (
            "error de filesystem ejecutando la operación Koha (%s); se omitieron datos sensibles" % exc.__class__.__name__)
        module.fail_json(msg=message, instance=name, state="unknown", db_mode=p["db_mode"],
                         changed=bool(actions), partial=bool(actions), actions=actions)


if __name__ == "__main__":
    main()
