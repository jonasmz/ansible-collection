# `jmz.koha.zebra_indexer`

Administra el demonio de indexación incremental Zebra de una instancia Koha
mediante `koha-indexer`. El indexador envía cambios al servidor Zebra; son
servicios distintos. El ciclo de vida del servidor se administra con
[`jmz.koha.zebra`](../zebra/README.md). Consulte los
[escenarios](examples.md) para ejemplos completos.

[Índice de módulos](../README.md) · [Guía general](../../README.md) ·
[README de la colección](../../../README.md)

## Parámetros

| Parámetro | Tipo | Requerido | Predeterminado | Descripción |
| --- | --- | --- | --- | --- |
| `instance` | string | sí | — | Nombre de instancia Koha válido (1–11 caracteres, minúsculas, números y guiones; comienza con letra). |
| `state` | string | condicional | — | `started`, `stopped`, `restarted` o `status`. Si se omite no cambia el proceso. |
| `enabled` | boolean | no | — | Habilitación persistente del servicio, independiente de `state`. |
| `quiet` | boolean | no | `false` | Pasa `--quiet` al comando. Los diagnósticos del módulo siguen disponibles. |
| `command_path` | path | no | `/usr/sbin/koha-indexer` | Ruta del comando oficial o de una instalación compatible. |
| `verify_zebra_engine` | boolean | no | `false` | Consulta la preferencia `SearchEngine` antes de iniciar o reiniciar; exige `Zebra`. |
| `require_zebra_running` | boolean | no | `false` | Exige Zebra activo antes de iniciar o reiniciar el indexador. |

Indique `state` o `enabled`. `state: status` no se combina con `enabled`.
`enabled: true` no arranca el daemon y `enabled: false` no lo detiene.

## Operación e idempotencia

`started` y `stopped` solo ejecutan la acción cuando la observación difiere.
`restarted` invoca siempre `koha-indexer --restart`, también si el proceso
está detenido, e informa cambio si la operación y su verificación concluyen.
La operación de reinicio de Koha es delegada al backend; se espera un proceso
iniciado y el módulo verifica ese resultado. `status` solo consulta.

Cuando se solicitan ambas propiedades, `enabled` se aplica primero al habilitar
y después se inicia; al deshabilitar, primero se detiene y luego se deshabilita.
El estado observado se comprueba después de cada acción. Una falla posterior a
una acción puede dejar un cambio parcial; el módulo devuelve los diagnósticos y
no intenta una reversión automática.

## Inspección, backends y compatibilidad

La validación comprueba el nombre seguro, `/etc/koha/sites/<instancia>/`, su
`koha-conf.xml` y la inclusión exacta en `koha-list`. Se requiere el ejecutable
`koha-indexer`. El backend systemd se identifica con el marcador de systemd y
la plantilla Koha de indexer instalada (con consulta de unidad como respaldo).
En systemd se usa `systemctl show` para observar `ActiveState` y `systemctl
is-enabled` para conservar estados como `masked`, `static` o `indirect` sin
inventar un booleano. El ciclo de vida sigue pasando por `koha-indexer`.

En SysV, estado y acciones usan `koha-indexer`; el estado se interpreta desde
`--status`, que delega en las comprobaciones de proceso de Koha asociadas a la
instancia, no desde un archivo PID aislado. SysV no ofrece enablement persistente
equivalente y una solicitud `enabled` falla. Para `enabled`, el módulo confirma
que la versión instalada anuncia `--enable`/`--disable` en `koha-indexer
--help` antes de ejecutarlos. Esta validación es necesaria porque la interfaz
cambia entre versiones.

Si se pide `verify_zebra_engine`, la preferencia se consulta con el mecanismo de
Koha `koha-shell` y `koha-preferences get SearchEngine`, sin mostrar ni extraer
credenciales. La lectura inconclusa falla explícitamente. `stopped` y `status`
siguen disponibles aunque el motor no sea Zebra. `require_zebra_running` consulta
la unidad Zebra exacta en systemd o el estado de `koha-zebra` en SysV; nunca
inicia Zebra. Esta inspección no certifica la salud ni la integridad de los
índices.

La fuente empaquetada de `koha-indexer` permite seleccionar
`ALTERNATE_INDEXER_DAEMON`. Antes de cualquier acción mutante el módulo lee ese
valor solo cuando es una asignación estática simple; si selecciona un ejecutable
alternativo o la configuración no se puede interpretar sin ejecutar shell, la
operación se rechaza. No cambia esa configuración. `USE_INDEXER_DAEMON`,
`INDEXER_TIMEOUT` e `INDEXER_PARAMS` son configuración operativa fuera del
alcance del módulo.

## Check mode y permisos

Soporta check mode con inspecciones de solo lectura. `planned_actions` contiene
las acciones previstas, mientras `state` y `enabled` conservan los valores
observados: no se presentan como estado hipotético alcanzado. Las acciones
requieren privilegios suficientes; use `become: true`.

## Resultado

Devuelve `instance`, `backend`, `state`, `previous_state`, `enabled`,
`previous_enabled`, `enablement_state`, `search_engine`, `zebra_running`,
`actions`, `planned_actions`, `diagnostics` y `msg`. Los estados runtime
normalizados son `started`, `stopped` y `unknown` (las transiciones de systemd
se consideran inconclusas para modificaciones). Los valores no verificables de
enablement se expresan como `null` más el estado crudo en `enablement_state`.

## Alcance y diferencias respecto de `jmz.koha.zebra`

Este módulo solo administra el daemon indexador de cambios incrementales.
`jmz.koha.zebra` administra el servidor de búsqueda Zebra. Ninguno debe
confundirse con reconstrucciones completas. El indexador no inicia ni detiene
Zebra; para coordinar ambos, administre Zebra explícitamente antes del indexador.

El módulo no ejecuta `rebuild_zebra.pl`, no reconstruye índices, no vacía colas,
no administra Elasticsearch o `koha-es-indexer`, ni modifica preferencias,
configuración, cron o parámetros de indexación.

## Requisitos y pruebas

Orientado a instalaciones Debian/Ubuntu empaquetadas de Koha. El entorno de
desarrollo de esta colección no tiene Koha instalado, así que no se declara una
versión de Koha verificada. Código Python estándar, `ansible-core >= 2.15` y
herramientas Koha del host; no agrega dependencias Python.

Prueba unitaria:

```console
python -m unittest tests.unit.test_zebra_indexer
```

La estrategia de integración segura está en
[examples.md](examples.md#validacion-de-integracion-en-debian-o-ubuntu).
