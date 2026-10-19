# `jmz.koha.localization`

Configura las preferencias de idioma de OPAC y Staff para una instancia Koha
ya inicializada. Utiliza `C4::Context->preference()` y
`C4::Context->set_preference()` desde un helper Perl separado que se ejecuta
por `koha-shell` en el contexto de la instancia. No actualiza la tabla de
preferencias mediante SQL.

[Índice de módulos](../README.md) · [Guía general](../../README.md) ·
[Ejemplos](examples.md)

## Requisitos y alcance

- Ejecute con `become: true` en un host Debian/Ubuntu con Koha y `koha-shell`.
- La instancia debe estar creada y tener la inicialización de base de datos
  completada. Se comprueba la preferencia `Version`, la existencia de
  preferencias en el esquema y el acceso efectivo a la base mediante las APIs
  de Koha; encontrar `koha-conf.xml` no basta.
- Las traducciones deben instalarse previamente con `jmz.koha.translate`.
  **`localization` no instala traducciones** ni cambia archivos de paquetes.
- La configuración se aplica a toda la instancia, no a cada biblioteca o
  sucursal. No configura idioma personal de usuario.
- No crea instancias, inicializa esquemas, configura Apache/Plack ni reinicia
  servicios.

El action plugin empaquetado con la colección transfiere `files/localization.pl`
a un directorio aleatorio temporal de `/tmp`, lo hace legible para el usuario
de instancia y elimina el directorio al finalizar. JSON se envía por stdin;
los datos no se incorporan al código Perl ni a argumentos del shell. El proceso
corre mediante `koha-shell INSTANCE -c ...`, que selecciona el usuario Koha,
`KOHA_CONF` y las rutas Perl de esa instancia.

## Parámetros

| Parámetro | Tipo | Obligatorio | Valores / comportamiento |
| --- | --- | --- | --- |
| `instance` | string | sí | Nombre Koha Debian: 1–11 caracteres, minúsculas, números o guiones; comienza con letra. |
| `staff_languages` | lista de strings | no | Códigos disponibles para Staff, orden preservado. |
| `opac_languages` | lista de strings | no | Códigos disponibles para OPAC, orden preservado. |
| `opac_language_selector` | boolean | no | `true` permite elegir idioma; `false` lo desactiva. |
| `opac_selector_position` | string | no | `top`, `footer` o `both`. |
| `staff_selector_position` | string | no | `top`, `footer` o `both`. |
| `state` | string | no | Solo `present`, valor predeterminado. |
| `timeout` | entero | no | Timeout de `koha-shell`, 120 segundos por omisión. |

Declare por lo menos una opción de configuración además de `instance` y
`state`. Las listas no pueden estar vacías, tener códigos duplicados ni códigos
malformados. Se mantienen exactamente el código, las mayúsculas y el orden.
Omitir un parámetro conserva su preferencia actual. Por ejemplo, configurar
solo `staff_languages` no cambia preferencias OPAC ni posiciones de selectores.

La posición pública corresponde a los valores internos de Koha `top`, `footer`
y `both` (la preferencia guarda `top|footer|both`). La opción booleana OPAC se
almacena como `1` o `0`. El selector Staff no tiene preferencia booleana propia:
Koha lo muestra de acuerdo con sus idiomas habilitados.

## Idioma predeterminado y disponibilidad

Koha guarda `StaffInterfaceLanguages` y `OPACLanguages` como códigos separados
por comas. El primer código conserva prioridad y es el idioma predeterminado
del sistema. El orden no se ordena alfabéticamente y reordenarlo es un cambio.
Koha también puede priorizar un idioma solicitado, cookie o selección de
sesión, o el encabezado de idiomas aceptados del navegador; no se garantiza
que la primera preferencia prevalezca sobre una elección personal válida.

El helper consulta `C4::Languages::getTranslatedLanguages` para la interfaz y
tema efectivos (Staff `template`, OPAC `opacthemes`) y no habilita un idioma sin
recursos reconocidos por Koha. `en` es el idioma fuente de Koha y no requiere
un paquete de traducción aparte. Un idioma ausente debe instalarse o repararse
con `jmz.koha.translate`; no se ejecuta esa instalación automáticamente.
Una traducción presente no garantiza traducción completa de todo el contenido
ni de personalizaciones locales.

## Compatibilidad Koha

| Versión declarada en `Version` | Preferencia Staff |
| --- | --- |
| anterior a 24.11 | `language` |
| 24.11 o posterior | `StaffInterfaceLanguages` |

La decisión combina la versión numérica (componentes major/minor, no una
comparación de cadenas) y la existencia efectiva de la preferencia en el
esquema instalado. Si la preferencia requerida no existe, falla antes de
escribir. Solo se modifica la preferencia de la rama activa. `OPACLanguages`,
`opaclanguagesdisplay`, `OpacLangSelectorMode` y `StaffLangSelectorMode` se
verifican en la base de la instancia. La documentación de Koha 24.11 confirma
el cambio de preferencia Staff; el manual documenta `top`, `footer`, `both` y
los valores sí/no para el selector OPAC.

La implementación se diseñó para las APIs presentes en las ramas 24.11 y
posteriores y conserva el nombre legado anterior a 24.11. En este workspace no
hay paquete Koha instalado para ejecutar la compatibilidad binaria; valide la
release exacta en una instancia de ensayo antes de producción.

Referencias primarias consultadas: [C4::Context](https://perldoc.koha-community.org/C4/Context.html),
[C4::Languages](https://perldoc.koha-community.org/C4/Languages.html),
[preferencias Staff de Koha 24.11](https://koha-community.org/manual/24.11/en/html/staffclientpreferences.html),
[preferencias de localización](https://koha-community.org/manual/latest/en/html/i18npreferences.html) y
[fuentes de Koha](https://github.com/Koha-Community/Koha).

## Idempotencia, check mode y diff mode

El helper lee el estado real y valida todas las preferencias e idiomas antes
de la primera escritura. Solo invoca `set_preference` para valores diferentes.
La escritura usa la API Koha, que actualiza la preferencia y su caché; no se
ejecuta una limpieza redundante ni se reinicia ningún servicio.

`--check` ejecuta las mismas consultas y validaciones, calcula el estado
proyectado y no escribe. `--diff` devuelve solo las opciones administradas por
esa invocación en `diff.before` y `diff.after`. En check mode, `changed` indica
si habría cambios y `planned: true` aclara que `after` es proyectado. En una
ejecución normal, `after` contiene los valores deseados que Koha confirmó.

Koha no ofrece una operación transaccional única para un conjunto de llamadas
`set_preference`. Si una escritura intermedia falla, el error incluye los
nombres actualizados en el helper; no se simula rollback porque podría borrar
cambios concurrentes. No se afirma atomicidad global.

## Retorno y errores

Devuelve `instance`, `koha_version`, `staff_preference`, `before`, `after`,
`updated_preferences`, `planned`, `changed` y `msg`. En ejecución normal,
`updated_preferences` contiene escrituras confirmadas; en check mode contiene
las preferencias que se escribirían. Los errores incluyen
instancia inválida/inexistente, inicialización incompleta, permisos, versión y
esquema incompatibles, preferencia ausente, idioma no instalado, timeout,
protocolo JSON inválido o error de Koha.

## Pruebas

Las pruebas unitarias cubren validadores, orden y configuración parcial,
protocolo JSON, límites de helper y separación del archivo Perl. No sustituyen
una integración con Koha. En este entorno no se ejecutó una instancia Koha;
consulte `examples.md` para una secuencia de integración aislada. Ejecútela solo
contra instancias descartables.
