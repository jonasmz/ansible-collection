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
| `timeout` | entero | no | Timeout de `koha-shell`, 120 segundos por omisión. |

Declare por lo menos una opción de configuración además de `instance`. Las listas no pueden estar vacías, tener códigos duplicados ni códigos
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
posteriores y conserva el nombre legado anterior a 24.11. El escenario de molecule
`translate_localization` (`extensions/molecule`) la ejecuta contra `koha-common
26.05.04` real; otras releases deben validarse en una instancia de ensayo antes de
producción.

Koha no guarda en la base de datos la lista de valores de `OpacLangSelectorMode` y
`StaffLangSelectorMode` (la columna `options` está vacía y las opciones viven en los
archivos `.pref` de las plantillas), por lo que el helper valida esas posiciones
contra la lista fija `top`, `footer` y `both`.

Referencias primarias consultadas: [C4::Context](https://perldoc.koha-community.org/C4/Context.html),
[C4::Languages](https://perldoc.koha-community.org/C4/Languages.html),
[preferencias Staff de Koha 24.11](https://koha-community.org/manual/24.11/en/html/staffclientpreferences.html),
[preferencias de localización](https://koha-community.org/manual/latest/en/html/i18npreferences.html) y
[fuentes de Koha](https://github.com/Koha-Community/Koha).

## Idempotencia, check mode y diff mode

El módulo planifica primero (una llamada al helper con `apply: false`) y solo escribe
si algo difiere, de modo que el check mode y una ejecución real coinciden y una
ejecución sin diferencias no escribe nada. El helper lee el estado real y valida
todas las preferencias e idiomas antes de la primera escritura, e invoca
`set_preference` solo para valores diferentes. No se reinicia ningún servicio.

`--check` ejecuta las mismas consultas y validaciones, calcula el estado
proyectado y no escribe. `--diff` devuelve solo las opciones administradas por
esa invocación en `diff.before` y `diff.after`. En check mode, `changed` indica
si habría cambios y `planned: true` aclara que `after` es proyectado. En una
ejecución normal, `after` contiene los valores deseados que Koha confirmó.

Las preferencias se escriben y se releen dentro de **una sola transacción**: se
aplican todas o ninguna. Si una escritura falla, se revierte todo, el error indica
`rolled back` y el resultado informa `updated_preferences: []`, `changed: false` y
`partial: false`. Tras la transacción se vacía la caché de preferencias para no
conservar valores leídos mientras estaba abierta.

Una ejecución mutadora toma un lock por instancia bajo `/run/lock`; una segunda
ejecución simultánea falla en lugar de competir. Si el helper es terminado (timeout)
o no devuelve JSON, el módulo vuelve a planificar para saber qué preferencias llegaron
a aplicarse e informa `updated_preferences`, `changed` y `partial` según ello (y de
forma conservadora si tampoco puede consultarlo). El stderr del helper, acotado y sin
caracteres de control, se incluye en el mensaje.

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
protocolo JSON, plan y apply, fallos sin respuesta y la separación del archivo Perl. El
escenario de molecule `translate_localization` los complementa contra Koha real:
check mode sin efectos, orden de idiomas, posiciones del selector, errores sin
cambios, atomicidad (un trigger de base de datos bloquea la segunda escritura y se
comprueba que la primera se revierte) y su interacción con `jmz.koha.initialize`.
`examples.md` incluye una secuencia de integración aislada; ejecútela solo contra
instancias descartables.
