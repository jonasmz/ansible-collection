# Escenario `translate_localization`

Prueba `jmz.koha.translate` y `jmz.koha.localization` contra el paquete real de
Koha (26.05) dentro de un contenedor Ubuntu 24.04 con systemd (podman), con la
imagen `localhost/koha-molecule:26.05` (ver `../image/build.sh`).

- `converge.yml` crea e inicializa la instancia e instala `es-ES`; la
  comprobación de idempotencia lo repite y exige `changed: 0`.
- `verify.yml` fija el comportamiento: ciclo completo de `translate` (check mode,
  instalar, repetir, `update`, quitar, idiomas inexistentes), `localization`
  sobre una instancia inicializada (check mode sin efectos, orden de idiomas,
  selectores, errores sin cambios) y su interacción con `initialize`.

Ejecución (desde la raíz de la colección):

```console
ANSIBLE_COLLECTIONS_PATH="$(mktemp -d):$HOME/.ansible/collections" molecule test -s translate_localization
```
