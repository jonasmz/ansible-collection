# Escenario `smtp_lifecycle`

Prueba `jmz.koha.smtp` contra el paquete real de Koha (26.05) dentro de un
contenedor Ubuntu 24.04 con systemd (podman), con la imagen
`localhost/koha-molecule:26.05` (ver `../image/build.sh`).

- `converge.yml` crea e inicializa la instancia; la comprobación de idempotencia
  lo repite y exige `changed: 0`.
- `verify.yml` fija el comportamiento: check mode sin efectos, creación, repetición,
  que Koha use el servidor como predeterminado (`get_default`), cambio de solo la
  contraseña (visible en el diff sin revelarla), normalización de `ssl_mode`,
  sustitución del predeterminado sin editar el anterior, host inválido, nombre
  duplicado, lock por instancia y que `koha-conf.xml` no cambie.

Ejecución (desde la raíz de la colección):

```console
ANSIBLE_COLLECTIONS_PATH="$(mktemp -d):$HOME/.ansible/collections" molecule test -s smtp_lifecycle
```
