# `jmz.koha.initialize`

Inicializa el esquema y los datos obligatorios de una instancia Koha y crea o
verifica sus entidades iniciales mediante las APIs Perl de Koha. Está orientado
a paquetes Debian/Ubuntu. No crea instancias ni administra Apache, Plack, Zebra,
workers, índices, cron o servicios externos.

[Índice de módulos](../README.md) · [Guía general](../../README.md) ·
[Ejemplos por escenario](examples.md)

## Requisitos y compatibilidad

- Colección `jmz.koha`, `ansible-core >= 2.15`, Python 3 en el host administrado
  y `koha-shell` instalado.
- Ejecutar con `become: true`. `koha-shell` debe poder cambiar al usuario
  `<instancia>-koha`; las credenciales DB se toman de esa misma instancia a
  través de `KOHA_CONF`.
- Si la instancia usa una zona horaria con nombre (`timezone` de `koha-conf.xml`),
  las tablas de zonas horarias de MariaDB deben estar cargadas antes de inicializar:
  ejecute [`jmz.koha.mariadb_timezone`](../mariadb_timezone/README.md). Este módulo
  ya no las carga ni reinicia MariaDB; si Koha no puede conectar por ese motivo, el
  error lo indica.
- El host debe tener `/etc/koha/sites/<instancia>/koha-conf.xml`, los archivos
  originales de instalación y las APIs Perl requeridas.
- El módulo inspecciona capacidades en ejecución y falla ante estados
  parciales; no ejecuta migraciones ni reinstala una base existente.
- Se revisaron los fuentes oficiales de las ramas 25.11.x y 26.05.x de
  `C4::Installer`. El escenario de molecule `initialize_lifecycle`
  (`extensions/molecule/`) ejecuta el módulo contra `koha-common 26.05.04` real:
  inspección, instalación e idempotencia, conflictos con entidades existentes,
  onboarding fallido y reanudado, timeout, check mode y zonas horarias. Otras
  versiones no se han probado; valide el paquete exacto en un host de ensayo.

El módulo y el helper Perl usan protocolo JSON versión 1. El action plugin copia
el helper versionado a un directorio temporal remoto, restringe sus permisos y
lo elimina al terminar. El JSON, incluida la contraseña inicial, viaja por
stdin, nunca por argv. El helper se ejecuta dentro de `koha-shell` para mantener
el contexto y el aislamiento de la instancia.

## Estado e idempotencia

`state: inspect` consulta la instancia sin modificar la base y no acepta parámetros de onboarding. `state: present`
es el predeterminado y realiza las fases permitidas:

| Estado detectado | Comportamiento |
| --- | --- |
| `uninitialized` | Puede crear esquema y datos en esta ejecución. |
| `schema_created` | Puede continuar solo si no se detectan datos de instalación aplicados. |
| `data_incomplete` | Falla y requiere evaluación manual. No repite SQL. |
| `onboarding_required` | Crea solo entidades declaradas que falten. |
| `initialized` | Verifica entidades y reglas declaradas; no modifica las que coinciden. |
| `upgrade_required` | Falla; actualizar Koha es otra operación. |
| `inconsistent` | Falla ante señales incompatibles o insuficientes. |

El esquema y las importaciones SQL no son transaccionales. En las fuentes de
Koha, `load_sql_in_order` vuelve a pasar por los SQL obligatorios al invocarse
otra vez y `FrameworksLoaded` solo representa los archivos que devolvieron sin
error. Por eso, si se interrumpe una carga después de comenzar, la siguiente
ejecución no la repite automáticamente. No borre la base para recuperarla.
Resuelva o restaure el estado con el procedimiento operativo correspondiente.

Las entidades y reglas se crean en una transacción DBIx cuando el motor permite
revertirlas. Las entidades existentes deben coincidir en los campos declarados;
una diferencia falla en vez de sobrescribir datos. La contraseña no se rota
para una cuenta existente. Para cambiarla utilice un flujo explícito de gestión
de credenciales de Koha.

El modo `--check` devuelve un plan real según el estado de la instancia:

- **`onboarding_required` o `initialized`:** el helper ejecuta el onboarding con las
  APIs de Koha dentro de una transacción que siempre se revierte. Informa las
  entidades y reglas que una ejecución real crearía (`changed`, `actions`,
  `partial: false`) y falla ante los mismos conflictos que una ejecución real.
  Una instancia ya inicializada con una entidad nueva declarada informa
  `changed: true`.
- **`uninitialized` o `schema_created`:** la instalación del esquema y de los datos
  es DDL no transaccional y no se puede simular. Se informan las acciones previstas
  con `partial: true` y sin verificar conflictos de entidades.
- Estados `data_incomplete`, `inconsistent` y `upgrade_required` fallan igual que
  en una ejecución real.

El action plugin copia el helper a un directorio temporal también en check mode
(es lo único que escribe en el host) y lo elimina al terminar; si no pudiera
eliminarlo, lo informa en `warnings`.

`--diff` expone solo el estado previo y posterior, nunca la contraseña.

## Parámetros

| Parámetro | Tipo | Obligatorio | Descripción |
| --- | --- | --- | --- |
| `instance` | string | sí | Identificador Koha (1–11 caracteres; minúsculas, números y guiones). |
| `state` | string | no | `present` (predeterminado) o `inspect`. |
| `language` | string | para `present` | Código que exista en el catálogo de idiomas instalado. Solo selecciona los datos del instalador: en una instancia ya instalada no se compara con los idiomas habilitados (los administra [`jmz.koha.localization`](../localization/README.md)) y, si no está habilitado, se emite una advertencia. |
| `marcflavor` | string | para `present` | `marc21` o `unimarc`, como en `jmz.koha.instance`; sin distinguir mayúsculas/minúsculas ni espacios externos (Koha lo almacena en mayúsculas); sujeto a frameworks disponibles. No existe el alias `marc_flavour`. |
| `sample_data` | lista | no | IDs opcionales `sección/archivo.sql` del catálogo de Koha; predeterminado vacío. |
| `library` | mapa | para `present` | `code`, `name`. No se reconcilia una biblioteca existente. |
| `patron_categories` | lista | para `present` | Categorías con `code`, `description`, `type`, `enrolment_period`, `default_privacy`. |
| `administrator` | mapa | para `present` | `username`, `firstname`, `surname`, `cardnumber`, `library`, `category`, `password` y `email` opcional. Solo `password` se marca `no_log`, de modo que los identificadores (código de biblioteca, usuario) siguen siendo legibles en mensajes y acciones. |
| `item_types` | lista | para `present` | Tipos con `code` y `description`; se exige al menos uno. |
| `circulation_rules` | lista | para `present` | Ámbito `library`/`category`/`item_type` y mapa explícito `rules`; no hay política predeterminada. |
| `timeout` | entero | no | Timeout del helper, 1800 segundos por omisión. |

La categoría del administrador debe ser tipo `S` (personal). La contraseña se
valida con `Koha::AuthUtils` y se almacena con `Koha::Patron::set_password`.
La elevación administrativa se obtiene con el mecanismo usado por el onboarding
de Koha y se verifica mediante `is_superlibrarian`.

Si se declara `administrator.email`, Koha lo valida y lo guarda como correo
principal del patron. En una cuenta existente sin correo, el módulo completa
ese dato; si la cuenta ya tiene una dirección distinta, falla para evitar
reemplazarla silenciosamente. Omitir `email` conserva el valor actual.
`administrator.email` es el correo del patron y no configura la preferencia
global `KohaAdminEmailAddress`.

Los nombres de `circulation_rules.rules` se normalizan a minúsculas antes de
invocar Koha, por lo que también se aceptan variantes camelCase como
`issueLength`. Los valores deben ser texto, número o booleano; un nombre mal escrito (por ejemplo `maxissuesqty`) se rechaza como regla desconocida. No se admiten códigos de categoría o tipo repetidos ni dos entradas para el mismo ámbito. Antes de
crear el esquema o cargar datos, el helper compara las reglas con el catálogo
de la versión Koha instalada y rechaza nombres desconocidos sin modificar la
base. Si una ejecución anterior ya llegó a `onboarding_required`, una nueva
ejecución retoma el onboarding y no repite el esquema ni los datos iniciales.

Los identificadores de `sample_data` se validan contra el catálogo de Koha y sus
rutas canónicas deben permanecer dentro de `installer/data`; no se aceptan rutas
SQL proporcionadas directamente. Los archivos de datos opcionales no se cargan
salvo autorización explícita.

## Matriz de investigación de APIs

| Operación | API y fuente upstream | Parámetros y resultado observado | Efectos, fallos e idempotencia | Compatibilidad/validación posterior |
| --- | --- | --- | --- | --- |
| Estado y conexión | `C4::Context->dbh`, `preference`, `needs_install`; `C4::Installer->new` en [25.11.x](https://github.com/Koha-Community/Koha/blob/25.11.x/C4/Installer.pm) y [26.05.x](https://github.com/Koha-Community/Koha/blob/26.05.x/C4/Installer.pm) | Contexto DB tomado de `KOHA_CONF`, configurado por `koha-shell`; `needs_install` es una señal complementaria. | Las consultas no modifican; el método no distingue por sí solo una instalación con datos incompletos. | Se verifica tabla base, `Version`, `marcflavour`, `FrameworksLoaded` y entidades básicas. Una conexión/grant ambiguos falla. |
| Crear esquema | `C4::Installer::load_db_schema` en `C4/Installer.pm`; carga el `kohastructure.sql` que provee el Koha instalado y devuelve texto de errores. | Sin argumentos; resultado textual de `load_sql`. | DDL no transaccional. Solo se llama sobre DB sin tablas; errores dejan el estado bloqueado para evitar repetir DDL. | Se verifica esquema/postcondición mediante Context y DBI de solo lectura. |
| Catálogo y carga de datos | `sample_data_sql_list($lang)`, `marc_framework_sql_list($lang,$flavour)`, `load_sql_in_order(...)`; [fuente 26.05.x](https://github.com/Koha-Community/Koha/blob/26.05.x/C4/Installer.pm) | Los catálogos devuelven listas por sección con `fwkfile` y `mandatory`. `load_sql_in_order` devuelve idioma y lista por archivo con errores. | Importa SQL/YAML y actualiza `FrameworksLoaded`; no es una transacción global y vuelve a ejecutar los archivos obligatorios. El helper se detiene ante cualquier error y no reintenta una carga iniciada. | Rutas canónicas restringidas al directorio de datos del paquete; opcionales identificados por sección/archivo y validados contra el catálogo. |
| Formato, idioma y versión | `set_marcflavour_syspref`, `set_languages_syspref`, `set_version_syspref` en `C4/Installer.pm`; ejecución desde [installer/install.pl](https://github.com/Koha-Community/Koha/blob/26.05.x/installer/install.pl). | Flavor primero; idioma después de carga; versión al cerrar datos fundamentales. | Cambios de preferencias y caché; `set_version_syspref` no se llama si hay errores de datos. | Se vuelve a observar la versión normalizada de Koha, flavor y `FrameworksLoaded`. |
| Biblioteca y categoría | `Koha::Library->new(...)->store` y `Koha::Patron::Category->new(...)->store`; [onboarding 26.05.x](https://github.com/Koha-Community/Koha/blob/26.05.x/installer/onboarding.pl) | Biblioteca requiere `branchcode/branchname`; categoría usa `categorycode`, `description`, `category_type`, `default_privacy`, `enrolmentperiod` y campos exigidos por el esquema. | Inserciones únicas; el onboarding web captura excepciones y solo avanza cuando existen colecciones no vacías. | Se encuentra por clave funcional, compara atributos declarados y falla ante drift; no actualiza implícitamente. |
| Administrador | `Koha::Patron->new(...)->store`, `Koha::AuthUtils::is_password_valid`, `Koha::Policy::Patrons::Cardnumber->is_valid`, `set_password`, `is_superlibrarian`; [onboarding 26.05.x](https://github.com/Koha-Community/Koha/blob/26.05.x/installer/onboarding.pl) | Identidad, biblioteca, categoría tipo `S`, `flags => 1`; contraseña entregada a `set_password`. Validación de contraseña devuelve `(is_valid,error)` y cardnumber devuelve resultado de validación. | Onboarding original no agrupa en una transacción la creación y password. El helper sí los envuelve en scope transaccional DBIx y no revela ni sustituye contraseña existente. | Revisa identidad existente y privilegio efectivo; crea dentro de transacción y verifica `is_superlibrarian`. |
| Tipo y circulación | `Koha::ItemType->new(...)->store`; `Koha::CirculationRules->get_effective_rule` y `set_rules`; [POD](https://perldoc.koha-community.org/Koha/CirculationRules.html) y [onboarding 26.05.x](https://github.com/Koha-Community/Koha/blob/26.05.x/installer/onboarding.pl). | Item type: `itemtype`, `description`; reglas: `{branchcode,categorycode,itemtype,rules}`. `rule_kinds` define nombres y ámbitos válidos. | Koha rechaza ámbitos inválidos; una regla exacta diferente no se pisa. Los cambios quedan en transacción y se verifica regla efectiva. | La combinación se compara y valida con las APIs reales de Koha; los valores no se inventan por defecto. |

La llamada realizada por `installer/install.pl` en las ramas 25.11.x y 26.05.x
es `load_sql_in_order($language, $all_languages, @files)`. El POD de
`C4::Installer` de ambas ramas muestra una firma incompleta/desactualizada que
omite el parámetro de idioma; el helper sigue la llamada efectiva del
instalador. La compatibilidad declarada para onboarding queda condicionada al
paquete instalado: se inspeccionó su fuente 26.05.x, pero no se pudo ejecutar
contra un paquete real en este entorno.

## Límites

- La detección de `initialized` comprueba indicadores de versión, frameworks,
  biblioteca, categoría de personal, superlibrarian, tipo de material y reglas.
  La verificación completa de los objetos declarados se hace durante
  `state: present`.
- Una carga SQL interrumpida es deliberadamente bloqueante. Koha no ofrece en
  estas APIs una garantía general de rollback o reanudación segura de todos los
  archivos de instalación.
- No es un actualizador de esquema. Una diferencia entre la versión de software
  y `Version` se clasifica como `upgrade_required` y requiere el procedimiento
  oficial de actualización.
- No carga registros bibliográficos demostrativos por omisión; inicializar no
  implica que el OPAC tenga resultados de catálogo.
- No se ejecutaron pruebas de integración contra Koha en este entorno: no están
  instalados Koha, MariaDB, `ansible-test` ni `ansible-core`.

## Retorno

Devuelve `instance`, `previous_state`, `current_state`, `actions`, `state_info`,
`validation` y, en `inspect`, `koha_version` y `capabilities`. Un fallo de Koha,
de la importación o de una postcondición termina la tarea con diagnóstico; no se
reporta éxito solo por código de salida cero.
