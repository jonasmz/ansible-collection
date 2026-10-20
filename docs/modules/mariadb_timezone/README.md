# `jmz.koha.mariadb_timezone`

Asegura que un MariaDB local conozca una zona horaria con nombre. Koha aplica la
zona IANA configurada (`timezone` de `koha-conf.xml`) a cada sesión MariaDB; si
las tablas de zonas horarias no existen, la conexión falla.

[Índice de módulos](../README.md) · [Guía general](../../README.md) ·
[Ejemplos](examples.md)

## Requisitos

- MariaDB local accesible por socket, su cliente (`mariadb` o `mysql`),
  `mariadb-tzinfo-to-sql` (o `mysql_tzinfo_to_sql`) y `tzdata`.
- `become: true`. Ejecute este módulo antes de `jmz.koha.instance` con `timezone`.

## Parámetros

| Parámetro | Tipo | Obligatorio | Semántica |
| --- | --- | --- | --- |
| `timezone` | string | sí | Zona IANA (`America/Argentina/Buenos_Aires`), `SYSTEM` u offset `±HH:MM`; los dos últimos no necesitan tablas. |
| `dbhost` | string | no | `localhost` (predeterminado) o loopback. Un host remoto falla: el módulo nunca modifica servidores remotos. |

## Comportamiento

Comprueba con `CONVERT_TZ`. Si MariaDB ya conoce la zona, devuelve
`changed: false`. Si no, carga las tablas desde `/usr/share/zoneinfo`, reinicia
MariaDB para activarlas y vuelve a comprobar. **El reinicio afecta a todas las
bases del servidor**; planifique la ejecución en consecuencia. Check mode solo
consulta e informa si se cargarían.

`jmz.koha.initialize` usa la misma utilidad para reparar las tablas de la zona
que figura en `koha-conf.xml` de la instancia.

Retorno: `timezone` y `loaded`.
