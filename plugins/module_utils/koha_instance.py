# SPDX-License-Identifier: MIT-0
"""Parameter validation and koha-create configuration helpers for the instance module."""

import re
import shlex


NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,10}$")
DB_RE = re.compile(r"^[A-Za-z0-9_]+$")
DB_PASSWORD_RE = re.compile(r"^[\x21-\x7e]{1,128}$")
DB_PASSWORD_UNSAFE = ":'&\\<>/"
DB_USER_RE = re.compile(r"^[A-Za-z0-9_]{1,32}$")
SAFE_SHELL_VALUE_RE = re.compile(r"^[^\x00\r\n]*$")


class ModuleInputError(ValueError):
    pass


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


def _validate_vhosts(vhosts):
    if not re.fullmatch(r"\.?[A-Za-z0-9.-]+", vhosts.get("domain") or ""):
        raise ModuleInputError("vhosts.domain es obligatorio y solo admite sufijo DNS opcional con punto inicial")
    for key in ("opac_prefix", "opac_suffix", "staff_prefix", "staff_suffix"):
        if vhosts.get(key) and not re.fullmatch(r"[A-Za-z0-9-]*", vhosts[key]):
            raise ModuleInputError("vhosts.%s solo admite caracteres DNS seguros" % key)
    for key in ("opac_port", "staff_port"):
        if vhosts.get(key) is not None and not 1 <= vhosts[key] <= 65535:
            raise ModuleInputError("vhosts.%s debe estar entre 1 y 65535" % key)


def _validate_db_credentials(credentials):
    username, password = credentials["username"], credentials["password"]
    if not DB_USER_RE.fullmatch(username) or not db_password_is_safe(password):
        raise ModuleInputError(
            "db_credentials requiere username [A-Za-z0-9_]{1,32}; password de 1-128 caracteres ASCII imprimibles "
            "sin espacios. Por seguridad de koha-create no se admiten : ' & / \\ < >")


def validate_params(p):
    """Validate a parameter set once; enum choices are enforced by the argument spec."""
    instance = p["instance"]
    mode = p["db_mode"]
    destructive = p.get("repair") or p.get("reconfigure")
    if not NAME_RE.fullmatch(instance or ""):
        raise ModuleInputError("instance debe tener 1-11 caracteres: minúsculas, números o guion; debe comenzar por letra")
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
    if (destructive or p.get("adopt")) and p["state"] != "present":
        raise ModuleInputError("repair, reconfigure y adopt solo son válidos con state=present")
    if p.get("adopt") and (destructive or mode not in ("create", "use")):
        raise ModuleInputError("adopt no se combina con repair/reconfigure ni con db_mode=request/populate")
    if destructive and mode not in ("create", "use"):
        raise ModuleInputError("repair/reconfigure no admiten db_mode=request ni populate; la DB existente se reutiliza con --use-db")
    if destructive and p.get("defaultsql"):
        raise ModuleInputError("repair/reconfigure no admiten defaultsql; --use-db conserva la DB existente y no importa SQL")
    if destructive and (p.get("confirm_instance") != instance or not p.get("confirm_data_loss")):
        raise ModuleInputError("repair/reconfigure requieren confirm_instance igual a instance y confirm_data_loss=true")
    if p.get("vhosts"):
        _validate_vhosts(p["vhosts"])
    if p.get("db_credentials"):
        _validate_db_credentials(p["db_credentials"])
    if mode == "request" and p.get("db_request_path") and not p["db_request_path"].startswith("/"):
        raise ModuleInputError("db_request_path debe ser una ruta absoluta del nodo remoto")
    if p.get("sru_port") is not None and not 1 <= p["sru_port"] <= 65535:
        raise ModuleInputError("sru_port debe estar entre 1 y 65535")
    port = (p.get("message_broker") or {}).get("port")
    if port is not None and port < 1:
        raise ModuleInputError("message_broker.port debe ser un entero positivo")
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
    for field in ("host", "username", "password", "vhost"):
        value = (p.get("message_broker") or {}).get(field)
        # Upstream expands these variables into sed replacement strings.
        # Refuse sed metacharacters that would alter generated Koha XML.
        if value is not None and any(ch in str(value) for ch in ("/", "&", "\\", "\r", "\n")):
            raise ModuleInputError("message_broker.%s contiene caracteres no soportados de forma segura por koha-create (/, &, backslash o salto de línea)" % field)


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


def build_argv(binary, mode, config_path, name):
    modes = {"create": "--create-db", "request": "--request-db", "populate": "--populate-db", "use": "--use-db"}
    argv = [binary, modes[mode], "--configfile", config_path, name]
    if len(argv) > 16:
        raise ModuleInputError("la combinación excede el límite nativo de 16 tokens de koha-create")
    return argv
