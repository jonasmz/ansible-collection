# Ejemplos de `jmz.koha.instance`

[Guía del módulo](README.md) · [Índice de módulos](../README.md) ·
[Guía general](../../README.md)

Todos los ejemplos asumen que la colección está instalada y que las tareas se
ejecutan en el servidor Koha con privilegios suficientes (`become: true`).
Los parámetros de contraseña deben venir de Ansible Vault o de otra fuente
segura; usa `no_log: true` en las tareas que los contienen.

## Crear una instancia con DB local

`create` es el modo predeterminado: crea la base de datos local y los recursos
de la instancia. Ajusta el flavor MARC y el idioma de Zebra según el catálogo.
`marcflavor` acepta cualquier combinación de mayúsculas/minúsculas (`MARC21`,
`Marc21`, `mArc21`) y la normaliza a `marc21`; los únicos valores admitidos son
`marc21` y `unimarc`.

```yaml
- name: Crear Koha biblioteca
  jmz.koha.instance:
    instance: biblioteca
    state: present
    db_mode: create
    marcflavor: marc21
    zebralang: es
  become: true
```

Una segunda ejecución con los mismos parámetros devuelve `changed: false` y no
invoca `koha-create`. Si los parámetros gestionados difieren, el módulo informa
drift y no los aplica silenciosamente.

## Crear detrás de HAProxy, con Memcached y message broker

Los vhosts se generan en la configuración de la instancia sin editar
`/etc/koha/koha-sites.conf`. HAProxy puede terminar TLS y enviar tráfico HTTP a
Apache en el puerto 80. Este módulo no configura HAProxy, SMTP ni Memcached.

```yaml
- name: Cargar las zonas horarias de MariaDB antes de crear la instancia
  jmz.koha.mariadb_timezone:
    timezone: America/Argentina/Buenos_Aires
  become: true

- name: Crear Koha detrás de HAProxy
  jmz.koha.instance:
    instance: biblioteca
    db_mode: create
    marcflavor: marc21
    zebralang: es
    timezone: America/Argentina/Buenos_Aires
    vhosts:
      domain: .example.org
      opac_port: 80
      opac_prefix: ""
      opac_suffix: ""
      staff_port: 80
      staff_prefix: ""
      staff_suffix: -admin
    memcached_enabled: true
    memcached_servers:
      - 127.0.0.1:11211
      timeout: 120
      debug: false
    message_broker:
      host: localhost
      port: 61613
      username: koha
      password: "{{ vault_broker_password }}"
      vhost: koha_biblioteca
    letsencrypt: false
  become: true
  no_log: true
```

Con estos valores, los nombres calculados son `biblioteca.example.org` para el
OPAC y `biblioteca-admin.example.org` para el personal. La contraseña del
broker se escribe en un configfile privado temporal, no en argv. Si omites
`message_broker`, Koha conserva sus valores globales o predeterminados. El
el módulo no administra SMTP durante el ciclo de vida; configura el correo de
la instancia ya creada con [`jmz.koha.smtp`](../smtp/README.md). `koha-create`
conserva sus opciones nativas de SMTP para el bootstrap inicial.

`opac_port` y `staff_port` configuran los puertos de los VirtualHost. No
configuran la dirección IP de escucha de Apache. El módulo actualmente no
expone una opción para fijar esa dirección; Koha la genera según la plantilla
Apache de la versión instalada y la directiva global `Listen` se administra en
la configuración de Apache del host (por ejemplo, `ports.conf`).

## Usar una base de datos existente

`use` conecta la instancia a una DB que ya debe existir y estar poblada. Si las
credenciales se proveen como `db_credentials`, el módulo prepara un archivo
temporal privado para Koha.

```yaml
- name: Crear instancia usando DB existente
  jmz.koha.instance:
    instance: biblioteca
    db_mode: use
    dbhost: db.example.org
    database: koha_biblioteca
    db_credentials:
      username: koha_biblioteca
      password: "{{ vault_koha_db_password }}"
  become: true
  no_log: true
```

También se puede proporcionar `passwdfile` con el formato nativo de Koha. No
definas `passwdfile` y `db_credentials` a la vez.
La contraseña DB admite símbolos comunes como `!@#$%` para poder usar
contraseñas aleatorias robustas. Debe ser ASCII imprimible sin espacios; el
módulo rechaza además los caracteres que el script nativo no puede interpolar
con seguridad.

```yaml
- name: Crear instancia con archivo nativo de credenciales
  jmz.koha.instance:
    instance: biblioteca
    db_mode: use
    database: koha_biblioteca
    passwdfile: /root/koha-secrets/biblioteca.passwd
  become: true
  no_log: true
```

Protege ese archivo en el host remoto (modo `0600`) y usa el formato
`instancia:usuario:contraseña:basedatos:host`.

## Flujo de solicitud y población de DB externa

`request` crea los recursos iniciales y escribe una solicitud de DB con
credenciales sensibles. La ruta se conserva para el administrador y el módulo
devuelve solo la ruta, nunca el contenido.

```yaml
- name: Preparar solicitud de base de datos externa
  jmz.koha.instance:
    instance: biblioteca
    db_mode: request
    db_request_path: /root/koha-db-requests/biblioteca-db-request.txt
  become: true
  no_log: true
```

Después de que el administrador de base de datos prepare esa DB y las
credenciales estén disponibles en el host Koha, completa la instalación:

```yaml
- name: Completar la instancia solicitada
  jmz.koha.instance:
    instance: biblioteca
    db_mode: populate
    database: koha_biblioteca
    db_credentials:
      username: koha_biblioteca
      password: "{{ vault_koha_db_password }}"
  become: true
  no_log: true
```

`populate` solo se acepta cuando el módulo reconoce la etapa `requested`.
Invocarlo sin una solicitud previa falla sin cambios.

## Personalizar SQL inicial y usuario administrativo

`defaultsql` selecciona un SQL inicial (incluidos formatos comprimidos
compatibles con el script instalado). `adminuser` es el ID del registro
administrativo que el script actualiza al importar el SQL; no crea una cuenta
de Koha.

```yaml
- name: Crear Koha desde SQL inicial propio
  jmz.koha.instance:
    instance: biblioteca
    db_mode: create
    defaultsql: /srv/koha/sql/initial.sql.gz
    adminuser: 1
  become: true
```

## Otras opciones de catálogo, SRU, cookies y rutas

Las opciones omitidas heredan los valores de Koha cuando corresponde. El
ejemplo muestra parámetros opcionales; verifica que el servicio relacionado
(por ejemplo Elasticsearch o Memcached) ya exista y sea accesible.

```yaml
- name: Crear Koha con opciones adicionales
  jmz.koha.instance:
    instance: archivo
    db_mode: create
    marcflavor: unimarc
    zebralang: fr
    elasticsearch_server: search.example.org:9200
    memcached_servers:
      - 127.0.0.1:11211
      - 127.0.0.2:11211
    memcached_prefix: archivo_
    enable_sru: true
    sru_port: 7091
    template_cache_dir: /var/cache/koha/archivo/templates
    upload_path: /srv/koha/archivo/uploads
    tmp_path: /srv/koha/archivo/tmp
    keep_cookies:
      - koha_language
      - koha_catalogue
  become: true
```

Configurar `elasticsearch_server` solo informa a Koha del servidor; no cambia
por sí mismo el motor de búsqueda Zebra a Elasticsearch.

## Heredar o componer configuración global

Si no defines `vhosts` ni parámetros específicos, Koha hereda su configuración
global. Puedes pasar un `configfile` Bash confiable del administrador; el
módulo lo carga antes de aplicar los overrides que genera para los parámetros
de esta tarea.

```yaml
- name: Crear con la configuración común del servidor
  jmz.koha.instance:
    instance: biblioteca
    db_mode: create
    configfile: /etc/koha/site-profiles/common.conf
    vhosts:
      domain: .example.org
      staff_suffix: -admin
      opac_port: 80
      staff_port: 80
  become: true
```

Koha carga `configfile` con Bash `source`. Solo usa archivos confiables y
controlados por el administrador; nunca construyas ese archivo con contenido
no confiable.

## Check mode

Con `--check`, el módulo informa el plan para una instancia ausente sin invocar
Koha ni escribir archivos. Para una instancia presente compatible informa que
no hay cambios. El check mode no valida servicios externos ni garantiza que
la creación vaya a completarse.

```yaml
- name: Revisar el plan de creación sin aplicarlo
  jmz.koha.instance:
    instance: biblioteca
    db_mode: create
    marcflavor: marc21
  become: true
  check_mode: true
```

## Let's Encrypt terminado en Apache local

Usa esta opción solo cuando Apache en el host Koha termina TLS directamente. El
módulo comprueba prerrequisitos, pero no instala el cliente ni resuelve prompts
interactivos. DNS público debe apuntar al host y el puerto 80 debe llegar a
Apache.

```yaml
- name: Crear Koha con certificado Let's Encrypt local
  jmz.koha.instance:
    instance: biblioteca
    db_mode: create
    vhosts:
      domain: .example.org
    letsencrypt: true
    tls_termination: local
  become: true
```

No uses `letsencrypt: true` cuando HAProxy u otro proxy termina TLS; esa
combinación falla intencionalmente.

## Reparar una instancia parcial

`repair` reconstruye la configuración de una instancia `partial` o `unmanaged`, preservando
la base de datos con `koha-remove --keep-mysql`. Exige repetir el nombre y
confirmar explícitamente el riesgo. Si la configuración existente no permite
recuperar la conexión a DB, proporciona credenciales válidas.

```yaml
- name: Reparar la configuración de biblioteca y preservar su DB
  jmz.koha.instance:
    instance: biblioteca
    repair: true
    confirm_instance: biblioteca
    confirm_data_loss: true
    db_credentials:
      username: koha_biblioteca
      password: "{{ vault_koha_db_password }}"
  become: true
  no_log: true
```

Revisa el resultado y conserva una copia recuperable de la DB antes de reparar.
La operación reconstruye archivos/configuración y reinicia Apache; no migra ni
recrea la DB.

## Reconfigurar preservando DB y datos

Para aplicar parámetros distintos a una instancia administrada y completa,
solicita `reconfigure` y las dos confirmaciones. El flujo retira y vuelve a
crear la configuración apuntando a la DB existente; conserva
`/var/lib/koha/<instance>` y no aplica `defaultsql`.

```yaml
- name: Cambiar los vhosts de biblioteca preservando DB y archivos
  jmz.koha.instance:
    instance: biblioteca
    reconfigure: true
    confirm_instance: biblioteca
    confirm_data_loss: true
    vhosts:
      domain: .example.org
      staff_suffix: -admin
      opac_port: 80
      staff_port: 80
    db_credentials:
      username: koha_biblioteca
      password: "{{ vault_koha_db_password }}"
  become: true
  no_log: true
```

No cambia ni migra el esquema o los datos de la base. Si falla el segundo paso
del backend, puede ser necesaria una reparación manual.

## Borrar una instancia

`state: absent` siempre exige doble confirmación. Por defecto elimina la
configuración de Koha pero conserva la base de datos y los datos de uploads.

```yaml
- name: Retirar biblioteca y conservar DB/datos
  jmz.koha.instance:
    instance: biblioteca
    state: absent
    confirm_instance: biblioteca
    confirm_data_loss: true
  become: true
```

Para pedir que `koha-remove` elimine la base de datos convencional
`koha_<instance>`, establece `remove_database: true`. Para eliminar también los
datos bajo `/var/lib/koha/<instance>` y spool, establece `purge_data: true`:

```yaml
- name: Retirar biblioteca y purgar DB convencional y datos locales
  jmz.koha.instance:
    instance: biblioteca
    state: absent
    confirm_instance: biblioteca
    confirm_data_loss: true
    remove_database: true
    purge_data: true
  become: true
```

`koha-remove` solo conoce la DB convencional `koha_<instance>`; verifica aparte
cualquier DB con nombre personalizado. Ejecuta primero en check mode para
revisar el plan. Si se conservan archivos locales, el módulo los informa como
residuales.

## Rutas no estándar de los ejecutables

Normalmente el módulo busca `koha-create` y `koha-remove` en el `PATH` o sus
ubicaciones habituales. Si el host usa rutas distintas, indícalas
explícitamente:

```yaml
- name: Crear una instancia usando un paquete Koha con rutas personalizadas
  jmz.koha.instance:
    instance: biblioteca
    db_mode: create
    koha_create_path: /opt/koha/bin/koha-create
  become: true

- name: Eliminar con koha-remove en una ruta personalizada
  jmz.koha.instance:
    instance: biblioteca
    state: absent
    confirm_instance: biblioteca
    confirm_data_loss: true
    koha_remove_path: /opt/koha/bin/koha-remove
  become: true
```
