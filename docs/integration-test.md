# Prueba integral de `jmz.koha`

El playbook [playbooks/integration.yml](../playbooks/integration.yml) crea
`codexqa26` como instancia de QA aislada, la inicializa con un superlibrarian,
construye los índices iniciales y habilita Plack, Zebra, el indexador y ambas
colas de workers. No borra instancias preexistentes. El password Koha se
solicita de forma privada en tiempo de ejecución y no se escribe en el repo.
El playbook habilita `rewrite` y `cgi` y recarga Apache antes de crear el sitio
si esos módulos aún están deshabilitados.
La inicialización usa el locale `en`, que está incluido en el paquete instalado.

El inventario [inventory/integration.ini](../inventory/integration.ini) apunta
a `10.27.49.248` con el usuario SSH `jonasmz` y usa la configuración SSH local
`/home/jonasmz/.ssh/config`. Ansible solicita el password become de forma
interactiva; no lo guardes en el inventario.

## Entorno y ejecución

La prueba se preparó con Python 3.14.8 y Ansible Core 2.21.5 en el entorno
aislado `/tmp/koha-ansible-venv`. La colección requiere Ansible Core 2.15 o
posterior.

```console
uv venv /tmp/koha-ansible-venv --python 3.14
uv pip install --python /tmp/koha-ansible-venv/bin/python ansible-core==2.21.5
cat > /tmp/koha-ansible.cfg <<'EOF'
[defaults]
collections_path = /tmp/ansible-collections
local_tmp = /tmp/ansible-local
remote_tmp = /tmp/ansible-remote
EOF
ANSIBLE_CONFIG=/tmp/koha-ansible.cfg /tmp/koha-ansible-venv/bin/ansible-galaxy collection build --force --output-path /tmp/koha-ansible-build
ANSIBLE_CONFIG=/tmp/koha-ansible.cfg /tmp/koha-ansible-venv/bin/ansible-galaxy collection install --force -p /tmp/ansible-collections /tmp/koha-ansible-build/jmz-koha-1.0.0.tar.gz
ANSIBLE_CONFIG=/tmp/koha-ansible.cfg /tmp/koha-ansible-venv/bin/ansible-playbook -i inventory/integration.ini playbooks/integration.yml --ask-become-pass
```

El playbook crea la instancia y los datos de onboarding indicados arriba.
Solicita el password inicial del superlibrarian dos veces, sin eco. El login es
`superlibrarian`; el password es el ingresado en ese prompt. Las URL se
construyen con DNS wildcard `sslip.io` para apuntar al IP de la VM.

La prueba ejecuta los siete módulos: `instance`, `initialize`, `plack`,
`zebra`, `zebra_rebuild`, `worker` y `zebra_indexer`. Repite las tareas
declarativas para comprobar idempotencia y exige respuesta HTTP del vhost de
personal. `zebra_rebuild` es una operación de escritura intencional que crea
los índices iniciales; no se repite porque no es idempotente.
El host usa el backend SysV para Zebra y el indexador, así que el ejemplo pide
estado `started` y omite `enabled`, que esos módulos no soportan en ese backend.
Para una revalidación posterior sin reconstruir índices, ejecute con
`-e '{"koha_run_initial_rebuild": false}'`.

## Resultados

Entorno local preparado: Python 3.14.8, Ansible Core 2.21.5 y colección
`jmz.koha:1.0.0` instalada en `/tmp`. La comprobación `ansible-playbook
--syntax-check` pasó.

La inspección remota confirmó Ubuntu 24.04.5, `koha-common 26.05.04-1`, Apache
y MariaDB activos, sin instancias Koha existentes. `mpm_itk` estaba cargado;
`rewrite` y `cgi` no estaban habilitados; el playbook los habilitó y recargó
Apache correctamente. En un esquema nuevo, `getAllLanguages()` devolvió un
catálogo vacío antes de cargar `subtag_registry.sql`; se ajustó el helper para
validar el locale contra los catálogos de instalación incluidos y admitir el
locale seleccionado durante la primera carga.

La integración terminó correctamente en `codexqa26` (Koha `26.05.04.000`).
`initialize` creó y verificó el login `superlibrarian` como superlibrarian en
la biblioteca `QA26`, categoría de personal `QASTAFF`. `plack`, Zebra, las
colas de workers y el indexador quedaron iniciados. Zebra completó una
reconstrucción inicial full de índices bibliográficos y de autoridades. El
backend de Zebra/indexer es SysV, así que no se solicitó `enabled`, opción no
soportada por ese backend. OPAC y personal respondieron HTTP 200 en la VM, y
`sslip.io` resolvió el nombre de personal a `10.27.49.248`.

La pasada final de idempotencia informó `ok=17 changed=0 failed=0 skipped=1`;
el único salto fue el rebuild full, omitido en la segunda pasada. La aserción
validó los estados, la respuesta HTTP y `changed: false` en las tareas
declarativas. `python3 -m unittest tests.unit.test_initialize -v` pasó sus 7
pruebas. Se corrigieron durante la integración la localización y staging del
helper Perl de la colección, el quoting para `koha-shell` y la validación de
idioma en un esquema nuevo.

URLs resultantes:

- Personal: <http://codexqa26-staff.10.27.49.248.sslip.io/>
- OPAC: <http://codexqa26-opac.10.27.49.248.sslip.io/>
