# Escenario `services_lifecycle`

Prueba `jmz.koha.plack`, `jmz.koha.zebra`, `jmz.koha.zebra_indexer`,
`jmz.koha.worker` y `jmz.koha.zebra_rebuild` contra el paquete real de Koha
(26.05) dentro de un contenedor Ubuntu 24.04 con systemd (podman), con la imagen
`localhost/koha-molecule:26.05` (ver `../image/build.sh`).

- `prepare.yml` habilita los módulos de Apache `headers` y `proxy_http`, que
  `koha-plack` necesita.
- `converge.yml` crea la instancia y deja Plack, Zebra, el indexer y los workers
  en marcha; la comprobación de idempotencia lo repite y exige `changed: 0`.
- `verify.yml` recorre el ciclo de vida de cada módulo (parar, repetir, arrancar,
  reiniciar, consultar con el servicio parado, check mode) y `zebra_rebuild`
  (incremental, completo silencioso y completo con salida).

Ejecución (desde la raíz de la colección):

```console
ANSIBLE_COLLECTIONS_PATH="$(mktemp -d):$HOME/.ansible/collections" molecule test -s services_lifecycle
```
