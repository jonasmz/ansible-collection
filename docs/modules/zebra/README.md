# `jmz.koha.zebra`

Administra el servidor Zebra de una instancia Koha con `koha-zebra`. Una instancia por tarea.
Requiere `become: true` para cambiar el servicio.

[Índice de módulos](../README.md) · [Guía general](../../README.md) ·
[Escenarios de uso](examples.md)

## Parámetros

| Parámetro | Tipo | Requerido | Valores | Descripción |
| --- | --- | --- | --- | --- |
| `instance` | string | sí | Identificador Koha | Instancia existente (1–11 caracteres: minúsculas, números o guiones; empieza por letra). |
| `state` | string | no | `started`, `stopped`, `restarted`, `status` | Estado deseado. Predeterminado: `status` (solo lectura). |
| `verbose` | boolean | no | `true`, `false` | Pasa `--verbose` a las operaciones de cambio. Predeterminado: `false`. |
| `timeout` | entero | no | segundos | Límite de cada llamada a un comando de Koha. Predeterminado: `60`. |

Los paquetes Debian de Koha no crean unidades systemd por instancia: el ciclo de vida
se gestiona con los scripts SysV (`daemon`) y el arranque al iniciar el sistema lo decide
`koha-common` para las instancias existentes. Por eso el módulo no ofrece `enabled`.

## Comportamiento

- `started` y `stopped` consultan el estado y actúan solo si difiere; `restarted` siempre reinicia
  (`changed: true`). `status` no cambia nada.
- El estado se lee de `koha-zebra --status` (`Zebra running for X` / `Zebra not running for X`) y,
  cuando no hay texto, del código de salida 3 (detenido).
- Tras cada operación se espera hasta 10 segundos a que el servicio alcance el estado pedido; si no
  llega, falla.
- Las operaciones de cambio toman un lock por instancia y esperan hasta 30 segundos si otra
  ejecución (de cualquiera de los módulos de servicio o `zebra_rebuild`) lo tiene.
- Los comandos se ejecutan con `timeout`, de modo que uno colgado no bloquea la tarea.
- Check mode consulta el estado real y devuelve el proyectado, sin ejecutar operaciones.

## Retorno

`instance`, `previous_state`, `state` (`started` o `stopped`; proyectado en check mode), `actions`
(lista de operaciones), `planned`, `diagnostics` (llamadas a Koha con salida acotada), `changed` y
`msg`. Si una operación falla, `changed` indica si el estado llegó a cambiar.

Ejemplos en [examples.md](examples.md). Pruebas unitarias en `tests/unit/test_zebra.py` y escenario
de molecule `services_lifecycle` contra Koha real.
