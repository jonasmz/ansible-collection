# `jmz.koha.smtp`

Administra el SMTP predeterminado XML, el marcador de correo saliente de Koha y
la preferencia global `KohaAdminEmailAddress` en una instancia existente. No
crea instancias ni administra Postfix, Exim u otro MTA.

[Índice de módulos](../README.md) · [Guía general](../../README.md) ·
[Ejemplos](examples.md)

## Requisitos y compatibilidad

- Debian/Ubuntu con Koha empaquetado, `koha-shell`, `koha-email-enable`,
  `koha-email-disable` y `/usr/share/koha/bin/admin/koha-preferences`.
- Ejecutar con `become: true` y después de `jmz.koha.initialize`.
- El módulo consulta `C4::Context->needs_install()` y falla antes de mutar si
  Koha aún requiere instalación.
- `files/smtp_probe.pl` es un helper Perl físico empaquetado en la colección.
  El action plugin lo copia temporalmente a `/tmp`, lo ejecuta en `koha-shell`
  y elimina el directorio. No se genera Perl dinámicamente.

La infraestructura del proyecto tiene evidencia de integración con
`koha-common 26.05.04-1`, pero no se pudo ejecutar una integración SMTP en este
checkout porque el entorno local no tiene Koha ni Ansible instalados. La rama
oficial `main` consultada no garantiza compatibilidad con todos los paquetes.
Valide la versión instalada y las APIs `needs_install`,
`Koha::SMTP::Servers->get_default` e `is_system_default` antes de producción.

## Parámetros

| Parámetro | Tipo | Obligatorio | Semántica |
| --- | --- | --- | --- |
| `instance` | string | sí | Identificador 1–11 caracteres, minúsculas/números/guiones, comienza con letra. No hay alias `name`. |
| `server` | mapa | no | Actualización parcial de `yazgfs/config/smtp_server`; omitido no modifica XML. |
| `server.host` | string | no | Host DNS válido. |
| `server.port` | entero | no | 1–65535; no se fijan puertos según TLS. |
| `server.timeout` | entero | no | Positivo. |
| `server.ssl_mode` | string | no | `disabled`, `ssl` o `starttls`. |
| `server.user_name` | string | no | Usuario SMTP; `""` lo limpia. |
| `server.password` | secreto | no | Contraseña; `""` la limpia. Marcada `no_log`. |
| `server.debug` | boolean | no | Depuración SMTP. |
| `admin_email_address` | string | no | Preferencia global; omitida no cambia. |
| `enabled` | boolean | no | Habilita o deshabilita el correo de Koha. |
| `timeout` | entero | no | Timeout de subprocess, predeterminado 60 s. |

Los campos omitidos en `server` conservan los valores actuales. El valor vacío
solo limpia usuario o contraseña cuando se declara expresamente. Use Ansible
Vault y `no_log: true` en tareas con secretos.

El XML se valida antes y después. Se modifican únicamente los bytes de texto de
los nodos SMTP, preservando comentarios y contenido ajeno. No se escribe si ya
coincide. La sustitución usa un temporal en el mismo directorio, mantiene
owner/group/mode, sincroniza archivo y directorio y conserva un hard link de
recuperación durante el reemplazo. El archivo y los directorios de instancia no
pueden ser enlaces simbólicos.

`ssl_mode: disabled` emite una advertencia de transporte no cifrado. No se
imponen puertos convencionales según TLS.

## Precedencia SMTP

La API oficial `Koha::SMTP::Servers->get_default` elige primero un SMTP
persistido en DB con `is_default=1`; si no existe, usa `smtp_server` de
`C4::Context->config`; sin ambos, aplica el default interno (`localhost:25`,
`disabled`). Los servidores asociados a bibliotecas se preservan y no se
administran.

Este módulo gestiona solo XML. Si se declara `server` y existe un default en
DB, falla antes de cualquier mutación: cambiar XML no cambiaría el SMTP
efectivo. Cuando no se pide modificar servidor, `smtp_effective_source` informa
`database`, `xml`, `koha_default` o `unknown`; se incluye advertencia para un
default DB. No existe backend DB en esta versión.

## Preferencia y estado de correo

El módulo lee `KohaAdminEmailAddress` con `koha-preferences get`, compara el
valor y escribe mediante `koha-preferences load` con YAML de una preferencia
por stdin. La utilidad oficial acepta stdin; no se pasa el valor por argv ni
se usa SQL. Se confirma el resultado después de escribir.

`enabled` llama a `koha-email-enable/disable <instance>` solamente si cambia
`/var/lib/koha/<instance>/email.enabled`, y confirma el estado posterior. Los
scripts oficiales pueden terminar con éxito para nombres desconocidos, por lo
que el módulo valida previamente la instancia. Habilitar correo no inicia un
servicio SMTP local.

## Idempotencia, check mode, diff y reinicio

El módulo inventaría XML, `email.enabled`, la preferencia solicitada y la fuente
SMTP efectiva antes de cambiar estado. El segundo ciclo sin drift devuelve
`changed: false`. Check mode lee y valida sin escribir, modificar preferencias
ni ejecutar comandos de habilitación.

El diff muestra solo campos solicitados y reemplaza cualquier contraseña por
`<redacted>`. El retorno no incluye XML completo, stdout/stderr crudos ni
argumentos de comandos.

Cambiar XML devuelve `restart_required: true` y
`restart_reason: smtp_config_changed`; no se reinicia nada automáticamente.
Los procesos persistentes pueden conservar configuración en memoria. Use un
handler explícito para los consumidores de su sitio; reiniciar Plack por sí
solo no garantiza que workers y procesos cron relean toda la configuración.
Cambiar la preferencia no solicita reinicio.

## Retorno

Incluye `instance`, `email_enabled`, `smtp_config_source`,
`smtp_effective_source`, `smtp_changed`, `email_enabled_changed`,
`admin_email_changed`, `restart_required`, advertencias y acciones. La dirección
administrativa solo se devuelve cuando fue solicitada. No se devuelven secretos.

## Investigación oficial y diferencias

- [`koha-create`](https://github.com/Koha-Community/Koha/blob/main/debian/scripts/koha-create)
  conserva opciones `--smtp-*` para bootstrap y crea el bloque XML. En este
  checkout `instance` no tiene campos SMTP; se mantiene el bootstrap nativo y
  la gestión posterior queda en `smtp`.
- [`koha-email-enable`](https://github.com/Koha-Community/Koha/blob/main/debian/scripts/koha-email-enable)
  crea `email.enabled`; [`koha-email-disable`](https://github.com/Koha-Community/Koha/blob/main/debian/scripts/koha-email-disable)
  lo elimina. Ambos pueden informar instancia desconocida y terminar con rc 0.
- [`koha-shell`](https://github.com/Koha-Community/Koha/blob/main/debian/scripts/koha-shell)
  envuelve `-c` en ejecución shell. El módulo envía un comando fijo sin datos
  del usuario.
- [`koha-preferences`](https://github.com/Koha-Community/Koha/blob/main/misc/admin/koha-preferences)
  documenta `get`, `set` y `load`; `load` acepta stdin y `set` devuelve rc 3 si
  el valor ya coincide. Se compara antes y se usa `load` por stdin.
- [`C4::Context`](https://perldoc.koha-community.org/C4/Context.html) documenta
  `needs_install`, preferencias y config.
- [`Koha::SMTP::Servers`](https://perldoc.koha-community.org/Koha/SMTP/Servers.html)
  documenta `get_default`; el código de `main` confirma precedencia DB, XML y
  default interno. [`Koha::SMTP::Server`](https://perldoc.koha-community.org/Koha/SMTP/Server.html)
  expone asociaciones a bibliotecas.

La rama oficial consultada es `main`; el proyecto tiene evidencia puntual con
Koha 26.05.04, pero no se verificaron en esta ejecución todas las variantes de
paquetes 25.11/26.05. La ruta empaquetada de `koha-preferences` se verifica en
runtime y puede variar en distribuciones derivadas.
