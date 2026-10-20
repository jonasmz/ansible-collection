# `jmz.koha.plack`

Administra el demonio Plack de una instancia Koha y su activación en Apache con `koha-plack`.
Requiere `become: true` para los cambios.

Mientras Plack no esté activado, la instancia se sirve por CGI. Plack acelera Koha sirviendo las
peticiones desde un proceso persistente detrás de Apache (`proxy_http`).

[Índice de módulos](../README.md) · [Guía general](../../README.md) ·
[Escenarios de uso](examples.md)

## Parámetros

| Parámetro | Tipo | Requerido | Valores | Descripción |
| --- | --- | --- | --- | --- |
| `instance` | string | sí | Identificador Koha | Instancia existente. |
| `state` | string | no | `started`, `stopped`, `restarted`, `reloaded`, `status` | Estado del demonio. Si se omite o es `status`, no se toca. |
| `enabled` | boolean | no | `true`, `false` | Activa o desactiva Plack en la configuración de Apache de la instancia. No combinable con `state: status`. |
| `reload_apache` | boolean | no | `true`, `false` | Recarga Apache (`graceful`) si esta ejecución cambió `enabled`. Predeterminado: `false`. |
| `timeout` | entero | no | segundos | Límite de cada llamada a un comando. Predeterminado: `60`. |

## `enabled`, `state` y Apache

`enabled` solo descomenta o comenta los dos `Include /etc/koha/apache-shared-{opac,intranet}-plack.conf`
del sitio de Apache de la instancia (lo hace `koha-plack --enable|--disable`). No arranca ni detiene
el demonio y **no recarga Apache**, que solo lee los `Include` al recargar. Por eso el resultado
incluye `apache_reload_required: true` cuando `enabled` cambió y Apache no se recargó. Hay dos formas
de recargarlo:

- `reload_apache: true`: el módulo ejecuta `apache2ctl graceful` tras el cambio.
- un `handler` del playbook que recargue Apache (el patrón usado con el módulo `instance`).

`state` y `enabled` son independientes: se aplican en el orden activar → demonio. En una misma tarea,
si activar funciona y el arranque falla, el fallo informa `changed: true` y las `actions` ya hechas.

## Prerrequisitos de Apache

`koha-plack` necesita los módulos `headers` y `proxy_http` (solo avisa por stderr si faltan). Antes
de activar Plack o de arrancar, reiniciar o recargar el demonio, el módulo comprueba con
`apache2ctl -M` y falla con `a2enmod headers proxy_http` como remedio si faltan. Desactivar Plack y
consultar no lo exigen.

## Comportamiento

- Idempotente: `started`, `stopped` y `enabled` solo actúan si difieren. `restarted` y `reloaded` son
  operaciones explícitas (`changed: true`).
- El estado se lee de `koha-plack --status` (`Plack running for X` / `Plack not running for X`). El
  módulo **no devuelve el `rc` de `--status`** (3 con el demonio parado), porque Ansible daría la
  tarea por fallida.
- Mismo lock por instancia y timeouts que [`jmz.koha.zebra`](../zebra/README.md). Check mode
  proyecta `running`, `enabled` y `apache_reload_required` sin ejecutar nada.
- Falla si falta el sitio de Apache, si los `Include` de OPAC e intranet no coinciden o si el estado
  no se puede interpretar.

## Retorno

`instance`, `running`, `enabled`, `previous_state`, `state` (`started`/`stopped`), `actions`,
`apache_reload_required`, `planned`, `diagnostics`, `changed` y `msg`.

Ejemplos en [examples.md](examples.md).
