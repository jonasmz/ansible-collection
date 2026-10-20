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
| `restart` | boolean | no | `false` por defecto. Reinicia MariaDB solo si la zona no se resuelve tras cargar las tablas. |
| `dbhost` | string | no | `localhost` (predeterminado) o loopback. Un host remoto falla: el módulo nunca modifica servidores remotos. |

## Comportamiento

Comprueba con `CONVERT_TZ`. Si MariaDB ya conoce la zona, devuelve
`changed: false`. Si no, carga las tablas desde `/usr/share/zoneinfo` y vuelve a
comprobar. En MariaDB 10.11 (verificado con Koha 26.05 en molecule) las tablas
cargadas se usan de inmediato, **sin reiniciar el servidor**: el módulo lo
comprueba comparando el `Uptime` antes y después.

Si tras la carga la zona sigue sin resolverse, falla e indica repetir con
`restart: true`. Solo con ese parámetro reinicia MariaDB, lo que **corta las
conexiones de todas las bases del servidor**. Está desactivado por defecto porque
otras versiones o MySQL podrían necesitarlo y no se han probado. Check mode solo
consulta e informa si se cargarían las tablas.

`jmz.koha.initialize` ya no carga estas tablas: si Koha no puede conectar por una
zona horaria desconocida, su error remite a este módulo.

Retorno: `timezone` y `loaded`.
