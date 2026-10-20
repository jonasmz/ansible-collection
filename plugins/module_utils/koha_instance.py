# SPDX-License-Identifier: MIT-0
"""Helpers for the instance module."""

import os
import re
import shlex
import grp
import pwd
import json


NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,10}$")
DB_RE = re.compile(r"^[A-Za-z0-9_]+$")
DB_PASSWORD_RE = re.compile(r"^[\x21-\x7e]{1,128}$")
DB_PASSWORD_UNSAFE = ":'&\\<>/"
SAFE_SHELL_VALUE_RE = re.compile(r"^[^\x00\r\n]*$")


class ModuleInputError(ValueError):
    pass


def normalize_marcflavor(value):
    """Normalize MARC flavor names for Koha's lowercase CLI values."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("marcflavor debe ser texto")
    return choice_normalizer(["marc21", "unimarc"])(value)


def choice_normalizer(choices):
    """Return a type converter that maps enum input to its canonical choice.

    Enum values are matched without regard to case or surrounding whitespace,
    then returned using the spelling declared in ``choices``.
    """
    canonical = {str(choice).strip().casefold(): choice for choice in choices}

    def normalize(value):
        if not isinstance(value, str):
            return value
        return canonical.get(value.strip().casefold(), value)

    return normalize


def db_password_is_safe(value):
    """Check the printable password subset safe for koha-create's SQL/XML/sed use."""
    return (isinstance(value, str) and DB_PASSWORD_RE.fullmatch(value) is not None
            and not any(char in value for char in DB_PASSWORD_UNSAFE))


def ensure_mariadb_timezone(module, timezone, dbhost):
    """Load local MariaDB timezone tables when a named Koha timezone is missing."""
    if not timezone or timezone == "SYSTEM" or re.fullmatch(r"[+-]\d{2}:\d{2}", timezone):
        return False
    if not re.fullmatch(r"[A-Za-z0-9_+-]+(?:/[A-Za-z0-9_+-]+)*", timezone):
        raise ModuleInputError("timezone debe ser SYSTEM, un offset ±HH:MM o un identificador IANA válido")
    host = (dbhost or "localhost").strip().lower()
    if host not in ("localhost", "127.0.0.1", "::1", "[::1]"):
        raise ModuleInputError("timezone %s requiere tablas MariaDB en la base remota %s; la carga automática requiere una DB local accesible por socket" % (timezone, dbhost))

    zoneinfo_root = os.path.realpath("/usr/share/zoneinfo")
    zone_file = os.path.realpath(os.path.join(zoneinfo_root, timezone))
    if not zone_file.startswith(zoneinfo_root + os.sep) or not os.path.isfile(zone_file):
        raise ModuleInputError("timezone %s no existe en %s" % (timezone, zoneinfo_root))

    client = module.get_bin_path("mariadb", required=False) or module.get_bin_path("mysql", required=False)
    if not client:
        raise ModuleInputError("no se encontró mariadb/mysql para comprobar las tablas de zonas horarias")

    query = "SELECT CONVERT_TZ('2025-01-15 12:00:00','+00:00','%s') IS NOT NULL" % timezone
    query_argv = [client, "--protocol=socket", "--batch", "--skip-column-names", "--execute", query, "mysql"]
    rc, stdout, _stderr = module.run_command(query_argv, check_rc=False)
    if rc != 0:
        raise ModuleInputError("no se pudo consultar MariaDB local como root para verificar las tablas de zonas horarias")
    if stdout.strip() == "1":
        return False
    if stdout.strip() != "0":
        raise ModuleInputError("MariaDB devolvió una respuesta inesperada al comprobar la zona horaria")

    tzinfo = module.get_bin_path("mariadb-tzinfo-to-sql", required=False) or module.get_bin_path("mysql_tzinfo_to_sql", required=False)
    if not tzinfo:
        raise ModuleInputError("no se encontró mariadb-tzinfo-to-sql/mysql_tzinfo_to_sql para cargar zonas horarias")
    rc, sql, _stderr = module.run_command([tzinfo, zoneinfo_root], check_rc=False)
    if rc != 0 or not sql:
        raise ModuleInputError("no se pudo generar la carga de zonas horarias desde %s" % zoneinfo_root)
    rc, _stdout, _stderr = module.run_command([client, "--protocol=socket", "mysql"], data=sql, check_rc=False)
    if rc != 0:
        raise ModuleInputError("MariaDB rechazó la carga automática de sus tablas de zonas horarias")

    systemctl = module.get_bin_path("systemctl", required=False)
    service = module.get_bin_path("service", required=False)
    if systemctl:
        rc, _stdout, _stderr = module.run_command([systemctl, "restart", "mariadb"], check_rc=False)
    elif service:
        rc, _stdout, _stderr = module.run_command([service, "mariadb", "restart"], check_rc=False)
    else:
        raise ModuleInputError("se cargaron zonas horarias pero no se encontró systemctl/service para reiniciar MariaDB y activarlas")
    if rc != 0:
        raise ModuleInputError("se cargaron las zonas horarias, pero no se pudo reiniciar MariaDB para activarlas")

    rc, stdout, _stderr = module.run_command(query_argv, check_rc=False)
    if rc != 0 or stdout.strip() != "1":
        raise ModuleInputError("las tablas de zonas horarias se cargaron, pero MariaDB no reconoce %s tras reiniciarse" % timezone)
    return True


def validate_params(p):
    instance = p.get("instance", p.get("name"))
    confirmed_instance = p.get("confirm_instance", p.get("confirm_name"))
    if p.get("marcflavor") is not None:
        p["marcflavor"] = normalize_marcflavor(p["marcflavor"])
    if not NAME_RE.fullmatch(instance or ""):
        raise ModuleInputError("instance debe tener 1-11 caracteres: minúsculas, números o guion; debe comenzar por letra")
    if p["state"] not in ("present", "absent"):
        raise ModuleInputError("state debe ser present o absent")
    mode = p["db_mode"]
    if mode not in ("create", "request", "populate", "use"):
        raise ModuleInputError("db_mode debe ser create, request, populate o use")
    if p.get("database") and (len(p["database"]) > 64 or not DB_RE.fullmatch(p["database"])):
        raise ModuleInputError("database debe contener hasta 64 letras, números o guiones bajos")
    if mode == "use" and not (p.get("database") or p.get("db_credentials") or p.get("passwdfile")):
        raise ModuleInputError("db_mode=use requiere database y credenciales en passwdfile o db_credentials")
    if p.get("db_credentials") and p.get("passwdfile"):
        raise ModuleInputError("db_credentials y passwdfile son mutuamente excluyentes")
    if mode == "populate" and any(p.get(k) for k in ("db_credentials", "passwdfile")):
        raise ModuleInputError("populate utiliza las credenciales ya presentes en koha-conf.xml; no acepte credenciales nuevas")
    if p.get("defaultsql") and mode not in ("create", "populate"):
        raise ModuleInputError("defaultsql solo es compatible con db_mode=create o populate")
    if p.get("adminuser") is not None and not p.get("defaultsql") and mode != "populate":
        raise ModuleInputError("adminuser solo tiene efecto con defaultsql en create o populate")
    if p.get("letsencrypt") and p.get("tls_termination") != "local":
        raise ModuleInputError("letsencrypt requiere declarar tls_termination=local; no lo use detrás de un proxy TLS")
    if p.get("letsencrypt") and p["state"] != "present":
        raise ModuleInputError("letsencrypt solo se aplica al crear/reconstruir una instancia present")
    if (p.get("remove_database") or p.get("purge_data")) and p["state"] != "absent":
        raise ModuleInputError("remove_database y purge_data solo se aplican con state=absent")
    if p.get("repair") and p.get("reconfigure"):
        raise ModuleInputError("repair y reconfigure son excluyentes")
    if (p.get("repair") or p.get("reconfigure")) and p["state"] != "present":
        raise ModuleInputError("repair y reconfigure solo son válidos con state=present")
    if (p.get("repair") or p.get("reconfigure")) and mode not in ("create", "use"):
        raise ModuleInputError("repair/reconfigure no admiten db_mode=request ni populate; la DB existente se reutiliza con --use-db")
    if (p.get("repair") or p.get("reconfigure")) and p.get("defaultsql"):
        raise ModuleInputError("repair/reconfigure no admiten defaultsql; --use-db conserva la DB existente y no importa SQL")
    if (p.get("repair") or p.get("reconfigure")) and (confirmed_instance != instance or not p.get("confirm_data_loss")):
        raise ModuleInputError("repair/reconfigure requieren confirm_instance igual a instance y confirm_data_loss=true")
    vhosts = p.get("vhosts") or {}
    if vhosts:
        if not re.fullmatch(r"\.?[A-Za-z0-9.-]+", vhosts.get("domain", "")):
            raise ModuleInputError("vhosts.domain es obligatorio y solo admite sufijo DNS opcional con punto inicial")
        for key in ("opac_prefix", "opac_suffix", "staff_prefix", "staff_suffix"):
            if vhosts.get(key) and not re.fullmatch(r"[A-Za-z0-9-]*", vhosts[key]):
                raise ModuleInputError("vhosts.%s solo admite caracteres DNS seguros" % key)
        for key in ("opac_port", "staff_port"):
            if vhosts.get(key) is not None and not 1 <= vhosts[key] <= 65535:
                raise ModuleInputError("vhosts.%s debe estar entre 1 y 65535" % key)
    if p.get("db_mode") == "request" and p.get("db_request_path") and not os.path.isabs(p["db_request_path"]):
        raise ModuleInputError("db_request_path debe ser una ruta absoluta del nodo remoto")
    if p.get("sru_port") is not None and not 1 <= p["sru_port"] <= 65535:
        raise ModuleInputError("sru_port debe estar entre 1 y 65535")
    for group, fields in (("message_broker", ("port",)),):
        for field in fields:
            value = (p.get(group) or {}).get(field)
            if value is not None and value < 1:
                raise ModuleInputError("%s.%s debe ser un entero positivo" % (group, field))
    if p.get("marcflavor") not in (None, "marc21", "unimarc"):
        raise ModuleInputError("marcflavor debe ser marc21 o unimarc; koha-create no admite none en la versión de referencia")
    if p.get("zebralang") not in (None, "cs", "el", "en", "es", "fr", "nb", "ru", "uk"):
        raise ModuleInputError("zebralang no está admitido por la versión de referencia de koha-create")
    if p.get("memcached_servers") and not all(re.fullmatch(r"[A-Za-z0-9_.:-]+", s) for s in p["memcached_servers"]):
        raise ModuleInputError("memcached_servers solo admite host:puerto con caracteres seguros")
    if p.get("memcached_prefix") and any(ch in p["memcached_prefix"] for ch in ("/", "&", "\\", "\r", "\n")):
        raise ModuleInputError("memcached_prefix contiene caracteres no seguros para la plantilla de koha-create")
    if p.get("keep_cookies") and not all(re.fullmatch(r"[A-Za-z0-9_-]+", x) for x in p["keep_cookies"]):
        raise ModuleInputError("keep_cookies solo admite nombres alfanuméricos, _ y -")
    for key in ("dbhost", "elasticsearch_server"):
        value = p.get(key)
        if value and not re.fullmatch(r"[A-Za-z0-9_.:\[\],-]+", value):
            raise ModuleInputError("%s contiene caracteres no admitidos" % key)
    for key in ("template_cache_dir", "upload_path", "tmp_path", "timezone"):
        value = p.get(key)
        if value and any(ch in str(value) for ch in ("#", "&", "\\", "\r", "\n")):
            raise ModuleInputError("%s contiene caracteres no seguros para la plantilla de koha-create" % key)
    if p.get("passwdfile") and re.search(r"\s", p["passwdfile"]):
        raise ModuleInputError("passwdfile no puede contener espacios; el script instalado expande esa ruta sin comillas")
    for group, fields in (("message_broker", ("host", "username", "password", "vhost")),):
        for field in fields:
            value = (p.get(group) or {}).get(field)
            # Upstream expands these variables into sed replacement strings.
            # Refuse sed metacharacters that would alter generated Koha XML.
            if value is not None and any(ch in str(value) for ch in ("/", "&", "\\", "\r", "\n")):
                raise ModuleInputError("%s.%s contiene caracteres no soportados de forma segura por koha-create (/, &, backslash o salto de línea)" % (group, field))


def shell_assignment(key, value):
    """Quote one Bash assignment. Values must remain single-line."""
    if not SAFE_SHELL_VALUE_RE.fullmatch(str(value)):
        raise ModuleInputError("un valor de configuración contiene NUL o salto de línea")
    return "%s=%s\n" % (key, shlex.quote(str(value)))


def config_values(p, request_passwdfile=None):
    """Return whitelisted shell variables understood by the upstream script."""
    values = {}
    v = p.get("vhosts") or {}
    for field, key in (("domain", "DOMAIN"), ("opac_port", "OPACPORT"),
                       ("opac_prefix", "OPACPREFIX"), ("opac_suffix", "OPACSUFFIX"),
                       ("staff_port", "INTRAPORT"), ("staff_prefix", "INTRAPREFIX"),
                       ("staff_suffix", "INTRASUFFIX")):
        if field in v and v[field] is not None:
            values[key] = v[field]
    if v:
        # koha-create may render an invalid *:None vhost if either port is
        # absent from koha-sites.conf. Default both public sites to HTTP.
        if values.get("OPACPORT") is None:
            values["OPACPORT"] = 80
        if values.get("INTRAPORT") is None:
            values["INTRAPORT"] = 80
    # CLO_* variables are applied after the configfile by the script and give
    # these explicit module parameters precedence over global Koha settings.
    mapping = {
        "marcflavor": "CLO_ZEBRA_MARC_FORMAT", "zebralang": "CLO_ZEBRA_LANGUAGE",
        "defaultsql": "CLO_DEFAULTSQL", "adminuser": "CLO_ADMINUSER",
        "dbhost": "CLO_DBHOST", "database": "CLO_DATABASE",
        "template_cache_dir": "CLO_TEMPLATE_CACHE_DIR", "timezone": "CLO_TIMEZONE",
        "upload_path": "CLO_UPLOAD_PATH", "tmp_path": "CLO_TMP_PATH",
        "elasticsearch_server": "CLO_ELASTICSEARCH_SERVER",
    }
    for source, dest in mapping.items():
        if p.get(source) is not None:
            values[dest] = p[source]
    if p.get("memcached_servers") is not None:
        values["CLO_MEMCACHED_SERVERS"] = ",".join(p["memcached_servers"])
    if p.get("memcached_prefix") is not None:
        values["CLO_MEMCACHED_PREFIX"] = p["memcached_prefix"]
    if p.get("memcached_enabled") is not None:
        values["USE_MEMCACHED"] = "yes" if p["memcached_enabled"] else "no"
    if p.get("enable_sru"):
        values["ENABLE_SRU"] = "yes"
    if p.get("sru_port") is not None:
        values["SRU_SERVER_PORT"] = p["sru_port"]
    broker = p.get("message_broker") or {}
    bmap = {"host": "CLO_MESSAGE_BROKER_HOST", "port": "CLO_MESSAGE_BROKER_PORT",
            "username": "CLO_MESSAGE_BROKER_USER", "password": "CLO_MESSAGE_BROKER_PASS",
            "vhost": "CLO_MESSAGE_BROKER_VHOST"}
    for source, dest in bmap.items():
        if broker.get(source) is not None:
            values[dest] = broker[source]
    if request_passwdfile:
        values["CLO_PASSWDFILE"] = request_passwdfile
    elif p.get("passwdfile"):
        values["CLO_PASSWDFILE"] = p["passwdfile"]
    if p.get("keep_cookies"):
        # Cookie names are constrained before being rendered as Bash array items.
        values["KEEP_COOKIE"] = list(p["keep_cookies"])
    if p.get("letsencrypt"):
        values["CLO_LETSENCRYPT"] = "yes"
    return values


def render_config(p, request_passwdfile=None):
    lines = []
    if p.get("configfile"):
        lines.append("source %s\n" % shlex.quote(p["configfile"]))
    for key, value in config_values(p, request_passwdfile).items():
        if key == "KEEP_COOKIE":
            lines.append("KEEP_COOKIE=(%s)\n" % " ".join(shlex.quote(x) for x in value))
        else:
            lines.append(shell_assignment(key, value))
    return "".join(lines)


def inspect_state(name, marker_path, request_path):
    paths = {
        "config": "/etc/koha/sites/%s/koha-conf.xml" % name,
        "apache": "/etc/apache2/sites-available/%s.conf" % name,
        "apache_enabled": "/etc/apache2/sites-enabled/%s.conf" % name,
        "site_dir": "/var/lib/koha/%s" % name,
    }
    found = {key: (os.path.lexists(path) if key == "apache_enabled" else os.path.exists(path)) for key, path in paths.items()}
    for key, lookup, function in (("user", name + "-koha", pwd.getpwnam), ("group", name + "-koha", grp.getgrnam)):
        try:
            function(lookup)
            found[key] = True
        except KeyError:
            found[key] = False
    try:
        with open(marker_path, "r", encoding="utf-8") as stream:
            marker_text = stream.read().strip()
            try:
                marker = json.loads(marker_text)
            except ValueError:
                marker = {"state": marker_text}
    except OSError:
        marker = {}
    if not any(found[key] for key in ("config", "apache", "apache_enabled", "user", "group")):
        return "absent", found, marker
    complete = all(found[key] for key in ("config", "apache", "site_dir", "user", "group"))
    if complete and marker.get("state") == "requested" and os.path.isfile(request_path):
        return "requested", found, marker
    if complete and marker.get("state") == "present":
        return "present", found, marker
    return "partial", found, marker


def build_argv(binary, mode, config_path, name):
    modes = {"create": "--create-db", "request": "--request-db", "populate": "--populate-db", "use": "--use-db"}
    argv = [binary, modes[mode], "--configfile", config_path, name]
    if len(argv) > 16:
        raise ModuleInputError("la combinación excede el límite nativo de 16 tokens de koha-create")
    return argv
