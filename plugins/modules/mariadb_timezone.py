#!/usr/bin/python
# SPDX-License-Identifier: MIT-0
"""Load the MariaDB timezone tables Koha needs for a named timezone."""

DOCUMENTATION = r'''
---
module: mariadb_timezone
short_description: Asegura las tablas de zonas horarias de un MariaDB local
description:
  - Comprueba con C(CONVERT_TZ) que MariaDB conoce la zona horaria indicada.
  - Si faltan las tablas, las carga desde C(/usr/share/zoneinfo) y reinicia MariaDB para activarlas.
  - Koha aplica su zona horaria IANA a cada sesión MariaDB; ejecute este módulo antes de M(jmz.koha.instance) con I(timezone).
  - Solo administra un MariaDB local accesible por socket; nunca modifica servidores remotos.
version_added: "1.3.0"
author: Jonas MZ
requirements:
  - MariaDB local, su cliente administrativo, C(mariadb-tzinfo-to-sql) y C(tzdata).
options:
  timezone:
    description: Zona IANA (por ejemplo America/Argentina/Buenos_Aires), C(SYSTEM) o un offset ±HH:MM; los dos últimos no requieren tablas.
    type: str
    required: true
  dbhost:
    description: Host de la base de datos; solo se admiten localhost y loopback.
    type: str
    default: localhost
'''

EXAMPLES = r'''
- name: Cargar zonas horarias antes de crear la instancia
  jmz.koha.mariadb_timezone:
    timezone: America/Argentina/Buenos_Aires
  become: true

- name: Previsualizar
  jmz.koha.mariadb_timezone:
    timezone: America/Argentina/Buenos_Aires
  become: true
  check_mode: true
'''

RETURN = r'''
timezone: {description: Zona horaria comprobada., returned: always, type: str}
loaded: {description: Si se cargaron (o se cargarían, en check mode) las tablas y se reinició MariaDB., returned: always, type: bool}
'''

import os

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.jmz.koha.plugins.module_utils.koha_instance import ModuleInputError
from ansible_collections.jmz.koha.plugins.module_utils.mariadb_timezone import ensure_mariadb_timezone


def main():
    module = AnsibleModule(argument_spec=dict(
        timezone=dict(type="str", required=True),
        dbhost=dict(type="str", default="localhost"),
    ), supports_check_mode=True)
    p = module.params
    try:
        if os.geteuid() != 0:
            raise ModuleInputError("la carga de zonas horarias MariaDB requiere root; ejecute la tarea con become: true")
        loaded = ensure_mariadb_timezone(module, p["timezone"], p["dbhost"], apply=not module.check_mode)
    except ModuleInputError as exc:
        module.fail_json(msg=str(exc), timezone=p["timezone"], loaded=False)
    module.exit_json(changed=loaded, timezone=p["timezone"], loaded=loaded,
                     msg="Tablas de zonas horarias cargadas." if loaded else "MariaDB ya conoce la zona horaria.")


if __name__ == "__main__":
    main()
