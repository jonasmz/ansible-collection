# `jmz.koha.smtp`

Agrega un servidor SMTP a la base de datos de una instancia Koha y lo establece
como predeterminado. Nada más: no modifica el servidor SMTP que Koha trae por
defecto (`smtp_server` en `koha-conf.xml`), no cambia `KohaAdminEmailAddress`,
no habilita ni deshabilita el correo saliente y no administra un MTA.

[Índice de módulos](../README.md) · [Guía general](../../README.md) ·
[Ejemplos](examples.md)

## Requisitos

- Debian/Ubuntu con Koha empaquetado y `koha-shell`.
- Una versión de Koha cuya tabla `smtp_servers` tenga `is_default`; el helper
  lo verifica antes de escribir y falla sin mutar si no existe.
- Ejecutar con `become: true` y después de `jmz.koha.initialize`.
- `files/smtp.pl` es un helper Perl empaquetado en la colección. El action
  plugin lo copia temporalmente a `/tmp`, lo ejecuta en `koha-shell` con la
  petición JSON por stdin y elimina el directorio. Usa las APIs
  `Koha::SMTP::Servers` y `Koha::SMTP::Server`, sin SQL.

## Parámetros

| Parámetro | Tipo | Obligatorio | Semántica |
| --- | --- | --- | --- |
| `instance` | string | sí | Identificador 1–11 caracteres, minúsculas/números/guiones, comienza con letra. No hay alias `name`. |
| `server` | mapa | sí | Servidor que será el predeterminado. |
| `server.name` | string | sí | Nombre en Koha; identifica el servidor para la idempotencia. |
| `server.host` | string | sí | Hostname DNS o IP válida. |
| `server.port` | entero | no | 1–65535; predeterminado `25`. |
| `server.smtp_timeout` | entero | no | Timeout de la conexión SMTP de Koha, en segundos (la columna `timeout` del servidor). Positivo; predeterminado `120`. |
| `server.ssl_mode` | string | no | `disabled` (predeterminado), `ssl` o `starttls`; ignora mayúsculas y espacios externos. |
| `server.user_name` | string | no | Predeterminado `""`. |
| `server.password` | secreto | no | Predeterminado `""`. Marcada `no_log`. |
| `server.debug` | boolean | no | Depuración SMTP; predeterminado `false`. |
| `timeout` | entero | no | Timeout de la llamada a `koha-shell`, predeterminado 120 s. No es el de la conexión SMTP (`server.smtp_timeout`). |

Use Ansible Vault y `no_log: true` en tareas con secretos.

## Comportamiento

- Si no existe un servidor con `server.name`, lo crea.
- Si existe, sus campos se reconcilian con los indicados (`server` es la
  declaración completa del servidor, no una actualización parcial).
- Lo marca como predeterminado. Si otro servidor de la base de datos lo era,
  solo se le quita esa marca: no se edita ni se elimina. Los servidores
  asociados a bibliotecas tampoco se tocan.
- El servidor de `koha-conf.xml` no se lee ni se escribe; Koha lo usa solo si
  la base de datos no tiene un predeterminado.
- Más de un servidor con el mismo nombre es un error; no se adivina cuál usar.
- Tras escribir, relee el estado desde Koha y verifica que el servidor tenga
  los valores pedidos y sea el único predeterminado.

## Idempotencia, check mode y diff

Una segunda ejecución con los mismos valores devuelve `changed: false`. Check
mode no escribe. El diff y el retorno nunca incluyen la contraseña; solo si hay
una almacenada. Si esta ejecución cambió la contraseña, `after.password` vale
`modificada` en lugar de `true`, para que el diff muestre el cambio sin revelarla.
Los cambios se aplican en una transacción de base de datos y bajo un lock por
instancia (espera hasta 30 s): la tabla `smtp_servers` no tiene índice único por
nombre, así que dos ejecuciones simultáneas podrían crear el mismo servidor dos veces.

Si la comprobación posterior a la escritura falla, los cambios ya están
confirmados y el fallo informa `changed: true`. Si `koha-shell` agota el
timeout, la transacción no llega a confirmarse y se puede reintentar. Los
errores de Koha se devuelven en español y sin la ruta del helper temporal.

No se reinicia ningún servicio. El servidor se lee de la base de datos en cada
envío, por lo que no requiere reiniciar Plack ni los workers.

## Retorno

`instance`, `server_id`, `created`, `updated`, `promoted`, `previous_default`
(cuando reemplaza a otro), `before` y `after`.
