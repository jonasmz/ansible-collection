# SPDX-License-Identifier: MIT-0
"""koha-create / koha-remove backend helpers for the instance module."""

import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET

from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import (
    DB_USER_RE, ModuleInputError, db_password_is_safe,
)


BACKUP_ROOT = "/var/backups"
SITES_ROOT = "/etc/koha/sites"
DB_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
DB_HOST_RE = re.compile(r"^[A-Za-z0-9_.:\[\]-]+$")
OPTION_FLAGS = {
    "marcflavor": "--marcflavor", "zebralang": "--zebralang", "elasticsearch_server": "--elasticsearch-server",
    "memcached_servers": "--memcached-servers", "memcached_prefix": "--memcached-prefix", "enable_sru": "--enable-sru",
    "sru_port": "--sru-port", "dbhost": "--dbhost", "database": "--database", "passwdfile": "--passwdfile",
    "defaultsql": "--defaultsql", "adminuser": "--adminuser", "template_cache_dir": "--template-cache-dir",
    "timezone": "--timezone", "upload_path": "--upload-path", "tmp_path": "--tmp-path", "keep_cookies": "--keep-cookie",
}
MODE_FLAGS = {"create": "--create-db", "request": "--request-db", "populate": "--populate-db", "use": "--use-db"}


def resolve_binary(module, explicit, name):
    """Return an executable path from an explicit override or the standard sbin/bin locations."""
    if explicit:
        if os.path.isfile(explicit) and os.access(explicit, os.X_OK):
            return explicit
        raise ModuleInputError("%s no es un ejecutable en el nodo remoto: %s" % (name, explicit))
    found = module.get_bin_path(name, required=False, opt_dirs=["/usr/sbin", "/usr/bin"])
    if not found:
        raise ModuleInputError("no se encontró %s; instale los paquetes Koha o defina %s_path" % (name, name.replace("-", "_")))
    return found


def _apache_modules(module):
    apachectl = (module.get_bin_path("apachectl", required=False, opt_dirs=["/usr/sbin"])
                 or module.get_bin_path("apache2ctl", required=False, opt_dirs=["/usr/sbin"]))
    if not apachectl:
        raise ModuleInputError("no se encontró apachectl/apache2ctl para comprobar Apache")
    rc, out, err = module.run_command([apachectl, "-M"], check_rc=False)
    if rc:
        raise ModuleInputError("no se pudo comprobar Apache antes de crear la instancia; revise apachectl -M y su configuración")
    return out + err


def check_apache_prerequisites(module):
    """Fail before koha-create mutates the host if Koha's Apache modules are absent."""
    modules = _apache_modules(module)
    for module_name, hint in (("mpm_itk_module", "Koha requiere mpm_itk habilitado en Apache; instale libapache2-mpm-itk y ejecute a2enmod mpm_itk"),
                              ("rewrite_module", "Koha requiere mod_rewrite habilitado en Apache; ejecute a2enmod rewrite y recargue Apache"),
                              ("cgi_module", "Koha requiere mod_cgi habilitado en Apache; ejecute a2enmod cgi y recargue Apache")):
        if module_name not in modules:
            raise ModuleInputError(hint)


def check_letsencrypt(module):
    if not module.get_bin_path("letsencrypt", required=False):
        raise ModuleInputError("letsencrypt=true requiere el ejecutable letsencrypt; instale/configure el cliente antes de ejecutar el módulo")
    rc, out, _ = module.run_command(["dpkg-query", "-W", "-f=${Status}", "letsencrypt"], check_rc=False)
    if rc or "install ok installed" not in out:
        raise ModuleInputError("letsencrypt=true requiere que el paquete Debian letsencrypt ya esté instalado; el módulo no instala paquetes ni acepta prompts")
    if "ssl_module" not in _apache_modules(module):
        raise ModuleInputError("letsencrypt=true requiere mod_ssl habilitado en Apache (a2enmod ssl)")


def require_options(module, binary, p, backend_mode, rebuild):
    """Fail before mutating when the installed koha-create lacks an option we would pass."""
    rc, out, err = module.run_command([binary, "--help"], check_rc=False)
    help_text = out + err
    needed = ["--configfile", MODE_FLAGS[backend_mode]]
    needed.extend(flag for key, flag in OPTION_FLAGS.items() if p.get(key))
    broker = p.get("message_broker") or {}
    needed.extend("--mb-%s" % key.replace("username", "user").replace("password", "pass")
                  for key, value in broker.items() if value is not None)
    if p.get("letsencrypt"):
        needed.append("--letsencrypt")
    if rebuild:
        needed.append("--passwdfile")
    missing = [flag for flag in needed if flag not in help_text]
    if missing:
        raise ModuleInputError("koha-create instalado no anuncia opciones requeridas (%s); compatibilidad no verificada" % ", ".join(missing))


def failure_hint(output):
    """Map common backend errors to fixed, non-sensitive diagnostics."""
    for pattern, hint in (
        (r"mpm_itk", "Koha requiere mpm_itk habilitado en Apache."),
        (r"mod_rewrite|rewrite_module", "Koha requiere mod_rewrite habilitado en Apache."),
        (r"mod_cgi|cgi_module", "Koha requiere mod_cgi habilitado en Apache."),
        (r"ERROR\s+1045|access denied", "MariaDB rechazó la autenticación; revise su configuración local sin compartir credenciales."),
        (r"ERROR\s+1044|command denied", "MariaDB rechazó los privilegios requeridos para crear la base de datos."),
        (r"ERROR\s+1007|database exists", "La base de datos convencional ya existe; inspecciónela antes de continuar."),
        (r"ERROR\s+2002|ERROR\s+2003|can't connect to.*server", "No se pudo conectar con MariaDB; revise que el servicio esté activo."),
        (r"can't locate .*\.pm|module .* not found", "Falta una dependencia Perl de Koha en el host."),
        (r"command not found|no such file or directory", "Falta un ejecutable o archivo requerido por Koha."),
        (r"permission denied|operation not permitted", "Koha encontró un problema de permisos en el host."),
    ):
        if re.search(pattern, output, re.IGNORECASE):
            return hint
    return "Revise los servicios y dependencias del host; la salida del backend se omitió por seguridad."


def vhost_hostnames(name, vhosts):
    """Build reported hostnames while treating omitted nested options as empty."""
    domain = vhosts["domain"].lstrip(".")
    opac = "%s%s%s.%s" % (vhosts.get("opac_prefix") or "", name, vhosts.get("opac_suffix") or "", domain)
    staff = "%s%s%s.%s" % (vhosts.get("staff_prefix") or "", name, vhosts.get("staff_suffix") or "", domain)
    return opac, staff


def write_private(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(content)
    os.chmod(path, 0o600)


def existing_db_credentials(config_path, name, credentials=None):
    """Read the DB record from Koha config, preferring explicitly supplied secrets."""
    try:
        root = ET.parse(config_path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise ModuleInputError("no se pudo leer koha-conf.xml (%s); proporcione db_credentials/passwdfile" % exc.__class__.__name__)
    # koha-conf.xml contains several unrelated <config> nodes inside its
    # embedded YAZ server definitions. The DB settings live in the Koha-level
    # config block, identified by its database/user/pass children.
    configs = [node for node in root.iter("config")
               if all(node.find(tag) is not None for tag in ("database", "user", "pass"))]
    if len(configs) != 1:
        raise ModuleInputError("koha-conf.xml no contiene un único bloque config con datos DB")
    config = configs[0]

    def value(tag):
        node = config.find(tag)
        return (node.text or "").strip() if node is not None else ""

    supplied = credentials or {}
    username = supplied.get("username") or value("user")
    password = supplied.get("password") or value("pass")
    database = value("database")
    host = value("hostname") or "localhost"
    if (not all((username, password, database)) or any("\n" in x or ":" in x for x in (username, password, database, host))
            or not DB_USER_RE.fullmatch(username) or not db_password_is_safe(password)
            or not DB_NAME_RE.fullmatch(database) or not DB_HOST_RE.fullmatch(host)):
        raise ModuleInputError("no se pudieron recuperar credenciales DB seguras del koha-conf.xml; proporcione db_credentials/passwdfile")
    return "%s:%s:%s:%s:%s\n" % (name, username, password, database, host)


def read_passwd_record(path, name):
    """Read and validate only the requested passwdfile row; never report contents."""
    try:
        with open(path, encoding="utf-8") as stream:
            rows = [line.rstrip("\r\n").split(":") for line in stream if line.startswith(name + ":")]
    except OSError as exc:
        raise ModuleInputError("no se pudo leer passwdfile (%s)" % exc.__class__.__name__)
    if len(rows) != 1 or len(rows[0]) != 5:
        raise ModuleInputError("passwdfile debe tener exactamente una fila Koha para la instancia solicitada con cinco campos")
    instance, username, password, database, host = rows[0]
    if (instance != name or not DB_USER_RE.fullmatch(username) or not db_password_is_safe(password)
            or not DB_NAME_RE.fullmatch(database) or not DB_HOST_RE.fullmatch(host)):
        raise ModuleInputError("passwdfile contiene valores no soportados de forma segura por koha-create")
    return rows[0]


def backup_instance(name):
    """Copy the instance configuration somewhere private before koha-remove deletes it."""
    root = tempfile.mkdtemp(prefix="ansible-koha-%s-" % name, dir=BACKUP_ROOT)
    os.chmod(root, 0o700)
    shutil.copytree("/etc/koha/sites/%s" % name, os.path.join(root, "sites"), symlinks=True)
    apache = "/etc/apache2/sites-available/%s.conf" % name
    if os.path.isfile(apache):
        shutil.copy2(apache, root)
    return root


def restore_site_config(name, backup, sites_root=SITES_ROOT):
    """Put the backed-up site directory back so a later repair can read its DB record.

    Only files missing from the live directory are restored; whatever a failed
    koha-create managed to write is left alone. Returns True when koha-conf.xml
    is available afterwards.
    """
    source = os.path.join(backup, "sites")
    target = os.path.join(sites_root, name)
    for directory, _, files in os.walk(source):
        destination = os.path.join(target, os.path.relpath(directory, source))
        os.makedirs(destination, exist_ok=True)
        for filename in files:
            if not os.path.lexists(os.path.join(destination, filename)):
                shutil.copy2(os.path.join(directory, filename), destination, follow_symlinks=False)
    return os.path.isfile(os.path.join(target, "koha-conf.xml"))
