# `jmz.koha.worker`

Administra los workers de background jobs de una instancia Koha con `koha-worker`: la cola
`default`, la cola `long_tasks`, o ambas con `all`. Requiere `become: true` para cambiar procesos.

Los workers ejecutan los trabajos en segundo plano que Koha encola en `background_jobs`
(importaciones, reindexados, informes, etc.); sin ellos esos trabajos se quedan pendientes.

[Índice de módulos](../README.md) · [Guía general](../../README.md) ·
[Escenarios de uso](examples.md)

## Parámetros

| Parámetro | Tipo | Obligatorio | Valores | Descripción |
| --- | --- | --- | --- | --- |
| `instance` | string | sí | Identificador Koha | Instancia existente. |
| `state` | string | no | `started`, `stopped`, `restarted`, `status` | Estado deseado. Predeterminado: `status` (solo lectura). |
| `queue` | string | no | `default`, `long_tasks`, `all` | Cola a administrar. Predeterminado: `default`. |
| `quiet` | boolean | no | `true`, `false` | Pasa `--quiet` a las operaciones de cambio. Predeterminado: `false`. |
| `timeout` | entero | no | segundos | Límite de cada llamada a un comando de Koha. Predeterminado: `60`. |

Los paquetes Debian de Koha no crean unidades systemd por instancia: el ciclo de vida
se gestiona con los scripts SysV (`daemon`) y el arranque al iniciar el sistema lo decide
`koha-common` para las instancias existentes. Por eso el módulo no ofrece `enabled`.

## Comportamiento

- Cada cola se gestiona por separado con `koha-worker --queue <cola>`; una cola que ya está en el
  estado pedido no se toca. `restarted` reinicia siempre las colas elegidas.
- El estado de cada cola se lee de `koha-worker --status` (`worker running for X (cola)` /
  `worker not running for X (cola)`).
- Mismo lock, timeouts y verificación posterior que [`jmz.koha.zebra`](../zebra/README.md). Si una
  cola falla, `changed` y `actions` conservan lo que ya se hizo en las anteriores.

## Retorno

`instance`, `queue`, `workers` (por cola: `previous_state`, `state` y `changed`), `actions`
(formato `operación:cola`, por ejemplo `start:long_tasks`), `planned`, `diagnostics`, `changed` y `msg`.

Ejemplos en [examples.md](examples.md).
