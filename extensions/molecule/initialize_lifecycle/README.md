# Escenario `initialize_lifecycle`

Prueba `jmz.koha.initialize` contra el paquete real de Koha (26.05) dentro de un
contenedor Ubuntu 24.04 con systemd (podman), reutilizando la imagen
`localhost/koha-molecule:26.05` (ver `../image/build.sh`).

- `converge.yml` crea la instancia e inicializa Koha; la comprobación de
  idempotencia lo repite y exige `changed: 0`.
- `verify.yml` fija el comportamiento: `inspect`, repetición sin cambios,
  conflictos con entidades existentes (biblioteca, categoría, tipo de material,
  regla exacta, administrador, MARC, regla desconocida), alta incremental, y un
  onboarding fallido (contraseña rechazada) que conserva los datos del instalador
  y se reanuda.

Ejecución (desde la raíz de la colección):

```console
ANSIBLE_COLLECTIONS_PATH="$(mktemp -d):$HOME/.ansible/collections" molecule test -s initialize_lifecycle
```
