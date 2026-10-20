# `jmz.koha.zebra_indexer`

Administra el demonio del indexador incremental de Zebra de una instancia con `koha-indexer`. Es
independiente del servidor Zebra (`jmz.koha.zebra`) y de la reconstrucción puntual
(`jmz.koha.zebra_rebuild`). Requiere `become: true` para cambiar el servicio.

[Índice de módulos](../README.md) · [Guía general](../../README.md) ·
[Escenarios de uso](examples.md)

## Parámetros

| Parámetro | Tipo | Requerido | Valores | Descripción |
| --- | --- | --- | --- | --- |
| `instance` | string | sí | Identificador Koha | Instancia existente. |
| `state` | string | no | `started`, `stopped`, `restarted`, `status` | Estado deseado. Predeterminado: `status` (solo lectura). |
| `quiet` | boolean | no | `true`, `false` | Pasa `--quiet` a las operaciones de cambio. Predeterminado: `false`. |
| `verify_zebra_engine` | boolean | no | `true`, `false` | Lee `SearchEngine` con `koha-shell` y solo permite arrancar o reiniciar si vale `Zebra`. Predeterminado: `false`. |
| `require_zebra_running` | boolean | no | `true`, `false` | Exige que el servidor Zebra de la instancia esté activo antes de arrancar o reiniciar. Solo lee; nunca arranca Zebra. Predeterminado: `false`. |
| `timeout` | entero | no | segundos | Límite de cada llamada a un comando de Koha. Predeterminado: `60`. |

Los paquetes Debian de Koha no crean unidades systemd por instancia: el ciclo de vida
se gestiona con los scripts SysV (`daemon`) y el arranque al iniciar el sistema lo decide
`koha-common` para las instancias existentes. Por eso el módulo no ofrece `enabled`.

`koha-create` arranca el indexador solo si `USE_INDEXER_DAEMON` es `yes` en `/etc/default/koha-common`
(valor predeterminado). Con ese valor `koha-rebuild-zebra` omite el trabajo incremental (lo hace el
indexador).

## Comportamiento

- Mismo ciclo, lock, timeouts y retorno que [`jmz.koha.zebra`](../zebra/README.md). Se añaden
  `search_engine` y `zebra_running` cuando se pidió comprobarlos.
- Si `ALTERNATE_INDEXER_DAEMON` está definido en `/etc/default/koha-common`, el módulo se niega a
  cambiar el estado, porque el demonio podría no ser el indexador de Zebra. Consultar sigue
  disponible. Solo se lee una asignación estática simple; el archivo nunca se ejecuta.
- Las comprobaciones previas fallan antes de cambiar nada: `SearchEngine` distinto de `Zebra`
  o Zebra detenido impiden arrancar o reiniciar, pero no parar ni consultar.

Ejemplos en [examples.md](examples.md).
