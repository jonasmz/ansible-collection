# SPDX-License-Identifier: MIT-0
"""Load MariaDB timezone tables so Koha's named timezones resolve."""

import os
import re

from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import ModuleInputError


def ensure_mariadb_timezone(module, timezone, dbhost, apply=True, restart=False):
    """Load local MariaDB timezone tables when a named Koha timezone is missing.

    Returns whether the tables were (or, with ``apply=False``, would be) loaded. MariaDB is only
    restarted when the zone still does not resolve after loading and ``restart`` is true.
    """
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

    if not apply:
        return True

    tzinfo = module.get_bin_path("mariadb-tzinfo-to-sql", required=False) or module.get_bin_path("mysql_tzinfo_to_sql", required=False)
    if not tzinfo:
        raise ModuleInputError("no se encontró mariadb-tzinfo-to-sql/mysql_tzinfo_to_sql para cargar zonas horarias")
    rc, sql, _stderr = module.run_command([tzinfo, zoneinfo_root], check_rc=False)
    if rc != 0 or not sql:
        raise ModuleInputError("no se pudo generar la carga de zonas horarias desde %s" % zoneinfo_root)
    rc, _stdout, _stderr = module.run_command([client, "--protocol=socket", "mysql"], data=sql, check_rc=False)
    if rc != 0:
        raise ModuleInputError("MariaDB rechazó la carga automática de sus tablas de zonas horarias")

    rc, stdout, _stderr = module.run_command(query_argv, check_rc=False)
    if rc == 0 and stdout.strip() == "1":
        return True
    if not restart:
        raise ModuleInputError("las tablas de zonas horarias se cargaron, pero MariaDB aún no reconoce %s; "
                               "repita con restart: true para reiniciar MariaDB y activarlas" % timezone)

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
