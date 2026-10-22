# Escenario `superlibrarian_recovery`

Prueba `jmz.koha.superlibrarian` contra el paquete real de Koha (26.05) dentro de
un contenedor Ubuntu 24.04 con systemd (podman), con la imagen
`localhost/koha-molecule:26.05` (ver `../image/build.sh`).

- `converge.yml` crea e inicializa la instancia (la comprobación de idempotencia
  lo repite y exige `changed: 0`).
- `verify.yml` sabotea la cuenta administradora como lo haría alguien con
  `staffaccess` (quita el privilegio, la vence, la bloquea, la restringe, cambia
  la contraseña y el apellido) y comprueba: check mode sin escritura, el
  restablecimiento completo y su idempotencia, que la contraseña vuelva a
  funcionar sin revelarse, que otro superlibrarian se avise sin modificarse (y se
  silencie con `allowed`), varias cuentas permitidas con el loop de la documentación (una llamada por cuenta con las demás en `allowed`: creación, idempotencia y reparación de solo la cuenta saboteada, sin bloquearse entre sí), la recreación de una cuenta borrada y los rechazos
  (categoría que no es de personal, biblioteca inexistente, contraseña débil).

Ejecución (desde la raíz de la colección):

```console
ANSIBLE_COLLECTIONS_PATH="$(mktemp -d):$HOME/.ansible/collections" molecule test -s superlibrarian_recovery
```
