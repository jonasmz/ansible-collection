# `jmz.koha.zebra`

Administra el servicio Zebra de una instancia Koha a través de `koha-zebra`.
La unidad de trabajo es una instancia por tarea. Consulte
[los escenarios de uso](examples.md) para playbooks listos para adaptar.

[Índice de módulos](../README.md) · [Guía general](../../README.md) ·
[README de la colección](../../../README.md)

## Parámetros

| Parámetro | Tipo | Requerido | Valores | Descripción |
| --- | --- | --- | --- | --- |
| `instance` | string | sí | Identificador Koha | Instancia existente, entre 1 y 11 caracteres en minúsculas, empezando por letra y seguido de letras, números o guiones. |
| `state` | string | no | `started`, `stopped`, `restarted`, `status` | Estado de ejecución deseado. Si se omite, no cambia el proceso. |
| `enabled` | boolean | no | `true`, `false` | Habilitación persistente del servicio Zebra, solo con unidad systemd compatible. |
| `verbose` | boolean | no | `true`, `false` | Agrega `--verbose` a las operaciones mutables. Predeterminado: `false`. |
| `command_path` | path | no | Ruta absoluta | Ruta de `koha-zebra`. Predeterminada: `/usr/sbin/koha-zebra`. |

Se debe indicar `state` o `enabled`. `state: status` es solo lectura y no se
combina con `enabled`. Los valores omitidos conservan su significado: omitir
`state` no cambia el proceso y omitir `enabled` no modifica la habilitación.

## Idempotencia y orden

`started` y `stopped` consultan el estado actual antes de actuar. Solo invocan
`koha-zebra --start` o `--stop` si hay una diferencia. `restarted` siempre
ejecuta `koha-zebra --restart` y marca `changed: true`. `status` consulta sin
cambiar el servicio.

El estado de ejecución y `enabled` son independientes. Si se solicitan ambos,
la habilitación ocurre antes de iniciar y la detención antes de deshabilitar.
El módulo verifica las postcondiciones; un código cero de `koha-zebra` no se
considera suficiente para afirmar éxito.

## Backends, permisos y check mode

Se comprueba la unidad específica `koha-zebra@<instancia>.service` para detectar
el backend systemd. Tener el ejecutable `systemctl` instalado no basta. En
systemd, el estado de ejecución y `UnitFileState` se consultan para esa unidad
exacta. `enabled` es booleano solo para los estados `enabled` y `disabled`;
estados como `masked`, `static` o `not-found` se devuelven por separado y no se
convierten en booleanos. No se intenta forzar esos estados a `true` o `false`.

El backend SysV se consulta mediante `koha-zebra --status`, que usa el
mecanismo de procesos de Koha. SysV no proporciona habilitación Zebra
persistente compatible con este módulo; solicitar `enabled` falla de forma
explícita y las consultas devuelven `enabled: null`.

Las modificaciones requieren privilegios de root. Use `become: true`. En
check mode se hacen consultas de solo lectura, se informa `changed` según el
plan calculado y `actions` contiene las operaciones previstas. No se ejecutan
operaciones mutables.

## Resultado

El resultado incluye `instance`, `backend`, `state`, `previous_state`,
`enabled`, `previous_enabled`, `enablement_state`, `actions`, `msg` y
`actions_status`, `diagnostics`. `actions_status` distingue `planned` en check
mode, `executed` al completar cambios, `attempted` en un fallo durante una
operación y `none` cuando no hubo acciones. Los estados runtime normalizados son `started` y `stopped`.
Una consulta ambigua o un fallo de postcondición produce un error, en lugar de
un estado inventado. En un fallo posterior a una operación, `changed` y
`actions` informan el cambio parcial; no se ejecuta una reversión automática.

## Requisitos y límites

- Debian o Ubuntu con `koha-zebra`, `koha-list` y una instancia Koha instalada.
- `ansible-core >= 2.15` y Python estándar del sistema, sin dependencias externas.
- En systemd, la unidad debe corresponder al nombre
  `koha-zebra@<instancia>.service`, como en las versiones empaquetadas que
  ofrecen servicios Koha por instancia. Las variantes antiguas se detectan
  como SysV si no hay una unidad específica cargada.
- No administra `koha-indexer`, índices, configuración Zebra ni
  `koha-conf.xml`; tampoco ejecuta `koha-rebuild-zebra` ni scripts de
  reindexación.

## Pruebas

Las pruebas unitarias usan mocks y no requieren Koha:

```console
python -m unittest tests.unit.test_zebra
```

La propuesta de validación en host real se documenta en
[examples.md](examples.md#prueba-de-integracion-en-debian-o-ubuntu).
