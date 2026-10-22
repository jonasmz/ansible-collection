# Escenario `user_permissions`

Prueba `jmz.koha.user` contra el paquete real de Koha (26.05) dentro de un
contenedor Ubuntu 24.04 con systemd (podman), con la imagen
`localhost/koha-molecule:26.05` (ver `../image/build.sh`).

- `converge.yml` crea e inicializa la instancia (la comprobación de idempotencia
  lo repite y exige `changed: 0`).
- `verify.yml` fija el comportamiento: check mode sin efectos, creación sin
  superlibrarian (flags y subpermisos en la base), idempotencia, login con la
  contraseña, permisos exactos (se revocan los no listados), cambio de perfil y
  contraseña sin revelarla, campos opcionales omitidos, módulo completo, cuenta
  sin permisos, rechazo de `superlibrarian`/módulos/subpermisos/biblioteca
  desconocidos y contraseña débil, negativa a tocar al administrador y lock por
  instancia.

Ejecución (desde la raíz de la colección):

```console
ANSIBLE_COLLECTIONS_PATH="$(mktemp -d):$HOME/.ansible/collections" molecule test -s user_permissions
```
