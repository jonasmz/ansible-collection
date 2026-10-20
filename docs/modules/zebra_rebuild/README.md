# `jmz.koha.zebra_rebuild`

Ejecuta de forma puntual `koha-rebuild-zebra` para una instancia: actualización incremental o
reconstrucción completa de los índices bibliográficos, de autoridades o ambos. Es una operación
imperativa; no administra Zebra ni el indexador. Requiere `become: true`.

[Índice de módulos](../README.md) · [Guía general](../../README.md) ·
[Escenarios de uso](examples.md)

## Parámetros

| Parámetro | Tipo | Requerido | Valores | Descripción |
| --- | --- | --- | --- | --- |
| `instance` | string | sí | Identificador Koha | Instancia existente. |
| `mode` | string | no | `incremental`, `full` | Predeterminado: `incremental`. |
| `target` | string | no | `all`, `biblios`, `authorities` | Predeterminado: `all`. |
| `force` | boolean | no | `true`, `false` | Pasa `--force` al incremental cuando `USE_INDEXER_DAEMON` está activo. No válido con `mode: full`. |
| `verbose` | entero | no | `0`–`3` | Banderas `--verbose`. Predeterminado: `1`. Use `0` con `quiet: true`. |
| `quiet` | boolean | no | `true`, `false` | Pasa `--quiet`; incompatible con `verbose` mayor que 0. |
| `verify_search_engine` | boolean | no | `true`, `false` | Exige `SearchEngine = Zebra`. Predeterminado: `true`. |
| `require_zebra_running` | boolean | no | `true`, `false` | Exige el servidor Zebra activo; nunca lo arranca. |
| `timeout` | entero | no | segundos | Límite de cada pasada de `koha-rebuild-zebra`. Predeterminado: `3600`. Las consultas usan 60. |

## Comportamiento

- Se validan antes de ejecutar nada: la instancia (`koha-list`), root, que `--help` anuncie cada
  opción pedida, `SearchEngine` y, si se pide, Zebra.
- `target: all` ejecuta dos pasadas, biblios y luego autoridades. Cada pasada se clasifica por
  separado en `target_results`; si una agota el timeout se marca `failed` y no se ejecutan las
  siguientes.
- **Incremental con el indexador activo.** Con `USE_INDEXER_DAEMON` distinto de `no` (valor
  predeterminado `yes`), Koha omite el trabajo incremental porque lo hace el indexador. El módulo lo
  informa con `status: skipped`, `work_skipped: true`, `changed: false` y **sin fallar**. La clave se
  llama `work_skipped` y no `skipped` porque Ansible mostraría la tarea como `SKIPPED`. Use
  `force: true` para forzarlo, o `mode: full`, que no depende de ese valor.
- **Salida vacía.** Una pasada con código 0 y sin diagnósticos conocidos cuenta como `completed`, también
  con `quiet: true` y `verbose: 0`, que no imprimen nada.
- **Clasificación.** Los diagnósticos específicos de Koha (fallos de reconstrucción, locks,
  trabajo omitido) se reconocen siempre. Las palabras genéricas (`error`, `failed`, `warning`) solo
  cuentan si el comando terminó con código distinto de 0, porque pueden aparecer en títulos de registros.
- Una ejecución real informa `changed: true`, incluso un incremental sin registros pendientes. Se toma
  el lock por instancia, que comparte con `zebra`, `zebra_indexer`, `worker` y `plack`, y Koha respeta
  además su propio lock de reconstrucción.
- Un código de salida 0 no prueba la integridad del índice ni da un recuento de registros.
- `USE_INDEXER_DAEMON` se lee como asignación estática simple de `/etc/default/koha-common`; un valor
  dinámico falla de forma segura.

## Retorno

`instance`, `mode`, `target`, `status` (`completed`, `skipped`, `blocked`, `failed`, `unknown`),
`executed`, `work_skipped`, `skip_reason`, `command`, `rc` (solo con un objetivo), `duration`,
`search_engine`, `zebra_running`, `target_results`, `stdout`, `stderr`, `diagnostics`, `changed` y `msg`.

Ejemplos en [examples.md](examples.md).
