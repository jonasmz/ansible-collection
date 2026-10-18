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
- El host debe tener `/etc/koha/sites/<instancia>/koha-conf.xml`, los archivos
  originales de instalación y las APIs Perl requeridas.
- El módulo inspecciona capacidades en ejecución y falla ante estados
  parciales; no ejecuta migraciones ni reinstala una base existente.
- Se revisaron los fuentes oficiales de las ramas 25.11.x y 26.05.x de
  `C4::Installer`; el entorno de desarrollo no tiene Koha instalado, por lo que
  no se declara una versión binaria probada. Antes de producción, valide el
  paquete exacto en un host de ensayo. APIs de onboarding también pueden variar
  entre releases.

El módulo y el helper Perl usan protocolo JSON versión 1. El action plugin copia
el helper versionado a un directorio temporal remoto, restringe sus permisos y
lo elimina al terminar. El JSON, incluida la contraseña inicial, viaja por
stdin, nunca por argv. El helper se ejecuta dentro de `koha-shell` para mantener
el contexto y el aislamiento de la instancia.

## Estado e idempotencia

`state: inspect` consulta la instancia sin modificar la base. `state: present`
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

El modo `--check` inspecciona el estado general y presenta un plan parcial. No
crea esquema ni objetos ni carga SQL, pero no puede anticipar conflictos de
atributos o reglas sin ejecutar la comparación de cada objeto; esos conflictos
se detectan durante la ejecución normal. `--diff` expone solo el estado previo
y posterior, nunca la contraseña.

## Parámetros

| Parámetro | Tipo | Obligatorio | Descripción |
| --- | --- | --- | --- |
| `instance` | string | sí | Identificador Koha (1–11 caracteres; minúsculas, números y guiones). |
| `state` | string | no | `present` (predeterminado) o `inspect`. |
| `language` | string | para `present` | Código que exista en el catálogo de idiomas instalado. |
| `marc_flavour` | string | para `present` | `MARC21` o `UNIMARC`, sujeto a frameworks disponibles. |
| `sample_data` | lista | no | IDs opcionales `sección/archivo.sql` del catálogo de Koha; predeterminado vacío. |
| `library` | mapa | para `present` | `code`, `name`. No se reconcilia una biblioteca existente. |
| `patron_categories` | lista | para `present` | Categorías con `code`, `description`, `type`, `enrolment_period`, `default_privacy`. |
| `administrator` | mapa | para `present` | `username`, `firstname`, `surname`, `cardnumber`, `library`, `category`, `password` y `email` opcional. La contraseña y el mapa se marcan `no_log`. |
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
