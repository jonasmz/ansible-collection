# Escenario `instance_lifecycle`

Prueba `jmz.koha.instance` contra el paquete real de Koha (26.05) dentro de un
contenedor Ubuntu 24.04 con systemd (podman). Recrea los fallos que motivaron la
refactorización del módulo:

- marcador privado y atómico (`schema_version: 2`), check mode coherente y drift;
- `adopt` de una instancia sin marcador;
- reconstrucción cuyo `koha-create` falla: configuración restaurada, respaldo
  conservado y `repair` posterior sin credenciales;
- `state: absent` de una instancia parcial sin `/etc/koha/sites/<instance>`.

## Imagen preconstruida

Instalar Koha en cada corrida tardaría demasiado, así que el escenario parte de
una imagen con Koha, MariaDB y Apache ya instalados. Se construye una sola vez
(y de nuevo solo para cambiar de versión de Koha):

```console
extensions/molecule/image/build.sh          # localhost/koha-molecule:26.05
extensions/molecule/image/build.sh 25.11    # otra versión (ajuste molecule.yml)
```

## Ejecución

Requiere `molecule`, `molecule-plugins[podman]`, `ansible-core` y podman.
Molecule instala la colección bajo prueba como copia en la primera ruta de
`ANSIBLE_COLLECTIONS_PATH`, así que use una ruta de trabajo y deje después las
colecciones de dependencias (`containers.podman`, `community.general`,
`ansible.posix`):

```console
ANSIBLE_COLLECTIONS_PATH="$(mktemp -d):$HOME/.ansible/collections" molecule test -s instance_lifecycle
```

Con la imagen preconstruida el ciclo completo tarda alrededor de un minuto.
`converge.yml` crea la instancia y la comprobación de idempotencia la repite;
`verify.yml` ejecuta los escenarios destructivos. Para iterar sin destruir el
contenedor: `molecule converge -s instance_lifecycle` y
`molecule verify -s instance_lifecycle`.
