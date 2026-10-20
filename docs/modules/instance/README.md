# `jmz.koha.instance`

Administra una instancia Koha con las utilidades empaquetadas `koha-create` y
`koha-remove`. Está orientado a instalaciones Debian/Ubuntu; no instala Koha ni
completa el onboarding desde la interfaz web.

[Índice de módulos](../README.md) · [Guía general](../../README.md) ·
[Ejemplos por escenario](examples.md)

Admite `state: present` y los modos nativos `create`, `request`, `populate` y
`use`. No configura HAProxy ni servicios externos.

La instancia se identifica con `instance` y las operaciones destructivas se
confirman con `confirm_instance`. No existen los alias `name` ni `confirm_name`,
y los resultados devuelven solo `instance`.

Los ejemplos de creación, bases de datos, vhosts, secretos, reparación,
reconfiguración y borrado están en la [guía de ejemplos](examples.md).

Instalación en el controlador: `ansible-galaxy collection install jmz.koha`.
Requiere Ansible Core 2.15+; el objetivo del proyecto es 2.19+. Ejecute en el
host Koha con `become: true`.

Antes de mutar, el módulo comprueba los módulos Apache exigidos por el
`koha-create` empaquetado: `mpm_itk`, `rewrite` y `cgi`. Si falta alguno,
falla antes de invocar el backend e indica el `a2enmod` necesario; habilitar
módulos y recargar Apache queda a cargo del administrador.

### Estados, idempotencia y check mode

El módulo inspecciona `koha-conf.xml`, el sitio Apache, el directorio de datos
y un marcador propio. Clasifica la instancia en cinco estados:

| Estado | Significado |
| --- | --- |
| `absent` | No existe ningún recurso de la instancia. |
| `requested` | Etapa `db_mode: request` completada; falta `populate`. |
| `present` | Completa y con marcador propio válido. |
| `unmanaged` | Completa pero sin marcador válido (creada a mano o por otra versión). |
| `partial` | Faltan recursos. |

En éxito guarda `/var/lib/koha/<instance>/.ansible-koha-instance-state` (modo 0600,
escritura atómica, `schema_version: 2`) con estado y huella de las opciones de
configuración no secretas. Los parámetros de operación (`db_mode`, rutas de
binarios, `db_request_path`, credenciales) no entran en la huella. Una repetición
idéntica no ejecuta `koha-create`; un cambio de configuración falla como drift.
Cambios externos en Apache/DB no se verifican y `present` no significa onboarding
web completado. Un marcador de otra versión del esquema no se reconoce: la
instancia pasa a `unmanaged` y se registra de nuevo con `adopt`.

Las mutaciones toman un lock por instancia (`/run/lock`); una segunda ejecución
simultánea falla en lugar de competir.

`--check` calcula el mismo plan que la ejecución real, sin exigir root ni
binarios, y no prueba dependencias ni servicios.

### Adoptar una instancia existente

Una instancia `unmanaged` no se modifica ni se reconstruye implícitamente. Con
`adopt: true` el módulo solo registra su marcador con la huella de los
parámetros declarados:

```yaml
- name: Registrar una instancia creada a mano
  jmz.koha.instance:
    instance: biblioteca
    adopt: true
    marcflavor: marc21
    zebralang: es
  become: true
```

`adopt` no verifica que la configuración real coincida con los parámetros: estos
pasan a ser la referencia para detectar drift. No hace nada si la instancia ya
está administrada y falla si está incompleta o requested. No se combina con
`repair`, `reconfigure`, `state: absent` ni `db_mode: request/populate`, y no
exige las confirmaciones destructivas porque no borra nada.

`timezone` solo se pasa a `koha-create`. Koha aplica esa zona IANA a cada sesión
MariaDB, así que las tablas de zonas horarias deben existir antes de crear la
instancia: use [`jmz.koha.mariadb_timezone`](../mariadb_timezone/README.md).

### Integración ejecutada

Prueba real del 2026-10-18 en `koha-test`: controlador Python 3.14.8 con
Ansible Core 2.21.5; host con `koha-common 26.05.04-1`, Apache
`2.4.58-1ubuntu8.17` y MariaDB `10.11.14-0ubuntu0.24.04.1`. El target usó
Python 3.12. Se creó `codexqa7`, se verificaron sus rutas Koha/Apache/datos,
la segunda aplicación devolvió `changed: false`, y luego se retiraron la
instancia, su DB y sus datos. La comprobación final confirmó que no quedaron
configuración, usuario Unix, grupo, DB ni directorio de datos. `rewrite` y
`cgi` estaban deshabilitados antes de la prueba; se habilitaron solo para
crear y se deshabilitaron y recargaron al terminar. `mpm_itk` ya estaba activo.

### Modos de base de datos

| `db_mode` | Flag nativo | Uso |
| --- | --- | --- |
| `create` | `--create-db` | DB nueva local y recursos Koha; predeterminado. |
| `request` | `--request-db` | Crea recursos y solicitud sensible de DB; no completa la instancia. |
| `populate` | `--populate-db` | Continúa solo una etapa `request` reconocida por marcador. |
| `use` | `--use-db` | Usa una DB ya creada y poblada. |

`request` escribe `db_request_path` o por defecto
`/var/lib/koha/<instance>/<instance>-db-request.txt`, modo 0600. Devuelve solo la ruta.
`db_credentials` se convierte a un `passwdfile` privado temporal nativo
(`instancia:usuario:contraseña:basedatos:host`) y no se combina con
`passwdfile`. Las filas de `passwdfile` se validan para el nombre solicitado.
El backend interpola estas credenciales en SQL sin escape: el
username debe ser `[A-Za-z0-9_]{1,32}`. La contraseña admite de 1 a 128
caracteres ASCII imprimibles sin espacios, incluidos símbolos como `!`, `@`,
`#`, `%` y `$`; por las interpolaciones sin escape del `koha-create` nativo,
se rechazan `:`, comilla simple, `&`, `/`, backslash, `<` y `>`. Las opciones
del message broker se guardan en un configfile temporal 0600, no en argv. El
script de referencia interpola algunos valores en sustituciones `sed`; por
seguridad se rechazan `/`, `&`, backslash y saltos de línea en credenciales y
campos de texto del broker. El módulo no expone opciones SMTP; configure el
correo de una instancia creada mediante [`jmz.koha.smtp`](../smtp/README.md).
Las opciones SMTP nativas de `koha-create` siguen disponibles para bootstrap,
pero no son el mecanismo de reconfiguración posterior. Añada `no_log: true`
a tareas con secretos.

### Configuración y precedencia

El módulo usa un archivo temporal privado y llama con modo, `--configfile` y
nombre (cinco tokens argv), inferior al límite 16 observado en la referencia.
Si define `configfile`, se carga primero como Bash confiable; después se aplican
overrides generados. El propio Koha ejecuta `source`, así que no use archivos
con datos de origen no confiable.

| Parámetro | Correspondencia/efecto |
| --- | --- |
| `marcflavor`, `zebralang` | `--marcflavor`, `--zebralang`; referencia admite marc21/unimarc y cs/el/en/es/fr/nb/ru/uk. |
| `elasticsearch_server` | `--elasticsearch-server`; no activa Elasticsearch como motor. |
| `memcached_servers`, `memcached_prefix` | `--memcached-servers`, `--memcached-prefix`. |
| `memcached_enabled` | Variable `USE_MEMCACHED`; omitida hereda global. |
| `enable_sru`, `sru_port` | Flags SRU; desactivado por omisión, puerto default 7090. |
| `database`, `dbhost`, `passwdfile` | `--database` (máx. 64), `--dbhost`, `--passwdfile`. |
| `defaultsql`, `adminuser` | `--defaultsql`, `--adminuser`; adminuser es ID borrower en importación SQL, no crea cuenta. |
| `template_cache_dir`, `timezone`, `upload_path`, `tmp_path` | Flags homónimos; omitidos para heredar defaults. Las tablas de zonas horarias de MariaDB no se cargan aquí. |
| `message_broker.*` | Opciones `--mb-*`; omitidas si no se definen. No gestiona el servicio externo. |
| `keep_cookies` | Repetición de `--keep-cookie`, serializada como array `KEEP_COOKIE`. |
| `vhosts.*` | Variables `DOMAIN`, `OPACPORT`, `OPACPREFIX`, `OPACSUFFIX`, `INTRAPORT`, `INTRAPREFIX`, `INTRASUFFIX`. Si se omite, hereda `koha-sites.conf`. |

`opac_port` y `staff_port` controlan el puerto del VirtualHost, no la IP de
escucha de Apache. La dirección de escucha no está expuesta por este módulo;
Apache la determina según su plantilla/configuración global del host.

`marcflavor` no distingue mayúsculas: `MARC21`, `Marc21` y `marc21` se
normalizan a `marc21` antes de validar o guardar el estado.

No se exponen `--help`, `--auth-idx` ni `--biblio-idx`. Las dos últimas aparecen
en getopt de la referencia, pero no se encontró procesamiento funcional.
`marcflavor: none` se rechaza porque no figura en su ayuda. `letsencrypt: true`
requiere TLS terminado en Apache local (`tls_termination: local`), paquete y
comando `letsencrypt` instalados, y `mod_ssl` habilitado. El módulo no instala
paquetes ni responde prompts. El backend solicita certificados y modifica y
reinicia Apache; DNS público debe apuntar al host y el puerto 80 debe llegar a
él. No lo use detrás de HAProxy/proxy que termina TLS (`tls_termination: proxy`).

### Borrado, reparación y reconfiguración explícitos

`state: absent` usa `koha-remove`. La operación exige dos confirmaciones:
`confirm_instance: biblioteca` y `confirm_data_loss: true`. Por defecto pasa
`--keep-mysql` para preservar la DB. `remove_database: true` permite que Koha
borre su DB convencional `koha_<instance>`; una DB con nombre personalizado puede
quedar intacta. `purge_data: true` agrega `--purge-all` y elimina datos de
`/var/lib/koha/<instance>` y spool. Sin `purge_data`, esos archivos se conservan y
se reportan como residuales.

`koha-remove` aborta si no existe `/etc/koha/sites/<instance>`. Para poder retirar
una instancia `partial` que perdió ese directorio, el módulo lo crea vacío antes
de invocarlo (`koha-remove` lo elimina de nuevo si queda vacío) y lo registra en
`actions`. Check mode no crea nada.

Si una instancia queda `partial` o `unmanaged`, `repair: true` reconstruye Apache y los
archivos Koha con `koha-remove --keep-mysql` seguido de `koha-create --use-db`.
Requiere las mismas dos confirmaciones y poder recuperar credenciales de
`koha-conf.xml`, o dar `db_credentials`/`passwdfile`. Para cambiar parámetros
de una instancia completa, `reconfigure: true` usa el mismo flujo y mantiene
la DB y `/var/lib/koha`. Ambos reinician Apache y reconstruyen la configuración;
no aplican `defaultsql` y no migran la base. Antes de `koha-remove` se copia
`/etc/koha/sites/<instance>` y el sitio Apache a un directorio privado en
`/var/backups`. Si `koha-create` falla, `koha-remove` ya habrá borrado el
usuario del sistema y el sitio Apache, que no se recrean solos, así que la
instancia queda `partial`. El módulo restaura en `/etc/koha/sites/<instance>` los
archivos de configuración que falten (para que un `repair: true` posterior pueda
leer las credenciales de `koha-conf.xml`), conserva el respaldo y lo indica en el
error; `actions` y `partial` reportan lo ya ejecutado. Si termina bien, el
respaldo se elimina. Requieren que el directorio del sitio exista, que `/var/backups` exista
y que `koha-remove` esté instalado. Use `--check` para revisar el plan antes.

```yaml
- name: Reconfigurar biblioteca manteniendo su base de datos
  jmz.koha.instance:
    instance: biblioteca
    reconfigure: true
    confirm_instance: biblioteca
    confirm_data_loss: true
    vhosts:
      domain: .example.org
      staff_suffix: -admin
  become: true

- name: Retirar la instancia y conservar DB/datos de uploads
  jmz.koha.instance:
    instance: biblioteca
    state: absent
    confirm_instance: biblioteca
    confirm_data_loss: true
  become: true
```

### Compatibilidad

En este checkout no estaban instalados `koha-create`, Ansible, `ansible-test` ni
`ansible-lint`. La fuente pública
[`koha-create` de Koha main](https://github.com/Koha-Community/Koha/blob/main/debian/scripts/koha-create)
fue consultada el 2026-10-18 y confirma límite `$# <= 16`, modos, precedencia,
variables, archivo request y prerequisites del flujo Let's Encrypt. El código
de [`koha-remove`](https://github.com/Koha-Community/Koha/blob/main/debian/scripts/koha-remove)
confirma `--keep-mysql` y `--purge-all`, incluyendo que el último elimina
`/var/lib/koha/<instance>` y spool. No sustituye verificar el paquete objetivo. En el
host Ubuntu 24.04 debe registrarse la versión exacta del paquete, revisar
`koha-create --help` y `/usr/share/koha/bin/koha-functions.sh`. El módulo
verifica en runtime que el binario anuncie modo y `--configfile`; las otras
opciones aún requieren validación con la versión empaquetada.

Se descartan stdout/stderr del backend porque pueden incluir claves generadas.
Las pruebas unitarias usan dobles del módulo/CLI; no se ejecutaron pruebas
Ansible ni de integración real en esta revisión.

### Pruebas unitarias

`python3 -m unittest discover -s tests/unit -v` ejecuta las pruebas unitarias
de la colección. Las pruebas de lógica usan dobles de los comandos Koha y no
requieren Koha ni privilegios root.
