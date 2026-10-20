# `jmz.koha.translate`

Asegura que una traducción de Koha esté instalada o ausente con el comando oficial
`koha-translate`. El módulo consulta el estado actual, ejecuta solo la operación
necesaria y verifica después la lista de idiomas instalados.

[Índice de módulos](../README.md) · [Guía general](../../README.md) ·
[Ejemplos](examples.md)

## Parámetros

| Parámetro | Tipo | Predeterminado | Descripción |
| --- | --- | --- | --- |
| `name` | string | obligatorio | Código exacto de idioma, por ejemplo `es-ES`. No tiene aliases. |
| `state` | string | `present` | `present` o `absent`. |
| `update` | boolean | `false` | Regenera la traducción cuando `state` es `present`. |
| `verbose` | boolean | `false` | Pasa `--verbose`. |
| `timeout` | entero | `600` | Segundos que puede ejecutarse cada llamada a `koha-translate` antes de ser terminada. Una mutación que lo excede devuelve `changed: true` y `partial: true`. |

Use `become: true`. El módulo exige un `koha-translate` ejecutable, los ayudantes de
Koha y los recursos de traducción; en los paquetes de Debian, `koha-l10n` suele
traer los archivos PO. El módulo no instala dependencias.

## Alcance

Koha escribe en su árbol compartido de aplicación Debian. La operación afecta a las
plantillas que usan todas las instancias, y los comandos de instalar y quitar limpian
la caché de las instancias habilitadas. No la repita en bucle por instancia de
producción. Los checkouts Git o de desarrollo (`koha-translate --dev`) no están
soportados: la antigua opción `dev_instance` se retiró porque no podía leer un
`koha-conf.xml` real.

## Estado e idempotencia

Con `state: present`, el módulo comprueba la lista exacta de instalados. Si el
idioma no está, comprueba la disponibilidad local y ejecuta `--check` de Koha antes
de `--install`. Si ya está instalado, no hace nada salvo que se pida `update: true`.

Con `state: absent`, un idioma ya ausente no cambia; uno instalado se quita y se
verifica su ausencia.

El idioma `en` se informa como instalado. Koha no permite instalarlo, actualizarlo
ni quitarlo.

Una actualización explícita es destructiva: el script de Koha elimina la traducción
anterior y la instala de nuevo. No es atómica; un error de instalación tras la
eliminación puede dejarla ausente. El módulo comprueba antes los archivos PO y
verifica el estado final, pero no simula un rollback. Como Koha no ofrece una
comprobación de revisión de las fuentes, `update: true` puede informar `changed` en
cada ejecución.

## Disponibilidad y archivos PO

`koha-translate --available` lista los códigos candidatos según los PO de OPAC. No
demuestra que estén todos los archivos necesarios. Antes de instalar o actualizar,
el módulo llama a `--check`, que verifica los PO de MARC21, UNIMARC, OPAC, preferencias
y personal. Un `--check` correcto tampoco demuestra que las plantillas generadas
funcionen.

Si un código no figura localmente, la interfaz oficial no distingue entre un idioma
desconocido y uno reconocido cuyos PO no están instalados. El módulo lo informa como
no disponible en los recursos locales e indica revisar `koha-l10n`.

## Check mode, diff y caché

El check mode hace solo consultas de lectura (ayuda, lista, disponibilidad y PO). Si
hace falta instalar, actualizar o quitar, devuelve `changed: true` y `planned_action`
sin invocar ninguna operación de modificación ni tomar el lock.

El diff muestra el estado semántico instalado antes y después; no lee ni muestra los
archivos generados. En una actualización marca la regeneración como prevista o
realizada, sin inventar versiones de traducción.

En el script de Koha 26.05.x, instalar y quitar limpian las cachés. La actualización
llama a las funciones internas de quitar e instalar, pero no llega a la limpieza de
caché del nivel superior. El módulo no ejecuta operaciones de caché adicionales.

Instalar plantillas no habilita `OPACLanguages` ni `StaffInterfaceLanguages`, no
cambia preferencias ni datos SQL, no configura usuarios ni inicializa una instancia.
Para activar los idiomas use [`jmz.koha.localization`](../localization/README.md).

## Resultados y errores

El módulo devuelve `name`, `state`, `installed`, `available`, `action_executed`,
`planned_action`, `cmd`, `rc`, `stdout`, `stderr` y `msg`. `available` es nulo si no
hizo falta consultar la disponibilidad. `cmd` es una lista argv segura, no una cadena
de shell, y la salida está acotada.

Distingue códigos inválidos, recursos locales no disponibles, PO incompletos, falta
del ejecutable, errores de la CLI, timeouts y estados finales no verificados. Un
fallo después de invocar un modificador, incluido un timeout, informa `changed: true`
y `partial: true`, porque las plantillas pueden haber quedado a medias; `installed`
refleja entonces lo que Koha lista. La salida de `koha-translate` se devuelve con los
bytes UTF-8 inválidos reemplazados (`fr-FR` imprime uno), de modo que ya no puede
romper el resultado.

Las llamadas que modifican usan un `flock` acotado en `/run/lock`, que espera hasta
30 s a otra operación del módulo. Solo coordina llamadas de este módulo, no comandos
externos de Koha.

## Compatibilidad

La implementación se revisó contra los scripts `koha-translate` de Koha 26.05.x y de
`main`, y el escenario de molecule `translate_localization` (`extensions/molecule`)
la ejecuta contra `koha-common 26.05.04` con `koha-l10n`: instalar, repetir,
actualizar, quitar, check mode, idiomas no disponibles, un timeout y la salida no
UTF-8 de `fr-FR`. Otras versiones requieren verificar el paquete instalado.

## Ejemplos

Vea [examples.md](examples.md). Las pruebas destructivas deben usar un laboratorio
Koha desechable y nunca producción.
