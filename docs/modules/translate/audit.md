# Auditoría y diseño de `translate`

## Repositorio

- La colección `jmz.koha` mantiene módulos auto-contenidos en `plugins/modules/`,
  documentación de uso en `docs/modules/<módulo>/` y pruebas `unittest` en
  `tests/unit/`. Las pruebas sustituyen `AnsibleModule` y simulan comandos
  Koha; no hay `pytest.ini`, `pyproject.toml` ni dependencias de test declaradas.
- El mínimo declarado es `ansible-core >= 2.15`. La documentación del despliegue
  probado registra Ubuntu 24.04.5 y Koha `26.05.04.000`; no declara una matriz
  más amplia de versiones Koha.
- `koha_instance.py` contiene validación y utilidades propias de instancias, pero
  no ofrece funciones de traducción reutilizables. `translate` no necesita
  modificarlo ni depender de módulos de gestión por instancia.
- Los módulos devuelven estructuras JSON con `exit_json`/`fail_json`, localizan
  comandos mediante `get_bin_path`, ejecutan argv con `run_command` y suelen
  ejecutar consultas previas/posteriores. Las pruebas usan `unittest.mock`.

## Fuentes y hallazgos de Koha

Fuentes examinadas el 2026-10-18:

- [`koha-translate` en Koha 26.05.x](https://raw.githubusercontent.com/Koha-Community/Koha/26.05.x/debian/scripts/koha-translate)
- [`koha-translate` en main](https://raw.githubusercontent.com/Koha-Community/Koha/main/debian/scripts/koha-translate)
- [`koha-functions.sh` en main](https://github.com/Koha-Community/Koha/blob/main/debian/scripts/koha-functions.sh)
- [Guía de desarrollo de módulos Ansible](https://docs.ansible.com/projects/ansible/latest/dev_guide/developing_modules_general.html)
- [Convenciones y prácticas de módulos Ansible](https://docs.ansible.com/projects/ansible/latest/dev_guide/developing_modules_best_practices.html)
- [Koha I18N advent](https://koha-community.gitlab.io/KohaAdvent/2025-12-02-i18n/)
- [Manual Koha: I18N/L10N](https://koha-community.org/manual/latest/en/html/i18npreferences.html)

El código consultado para `26.05.x` y `main` presenta la misma interfaz relevante
para este módulo: lista instalada/disponible, comprueba PO, instala, actualiza,
elimina, acepta `--verbose` y `--dev`, y rechaza más de cuatro argumentos de
consola. Esta similitud observada no constituye garantía de compatibilidad con
todas las revisiones empaquetadas; el código instalado sigue siendo la autoridad.

Hallazgos que afectan el diseño:

1. `--list` excluye `en` de la salida. En Koha 26.05.x, si no hay otras
   traducciones instaladas, el `grep` final no encuentra coincidencias y, por
   `set -e`, el comando termina con código 1 y salida vacía. El módulo trata
   únicamente ese resultado sin diagnósticos como una lista instalada vacía;
   otros códigos no cero siguen siendo errores.
2. La lista instalada se deriva de directorios OPAC `bootstrap` y `prog`; la
   disponible se deriva de nombres `*-opac-bootstrap.po`. Koha usa códigos
   regionales exactos como `es-ES`, `fr-CA` y `en-GB`; hay que comparar líneas
   completas, nunca subcadenas.
3. `--check LANG` verifica la existencia de cinco ficheros: MARC21, UNIMARC,
   OPAC bootstrap, preferencias y staff prog. No verifica funcionalidad ni
   estado instalado. `--available` solo prueba que existe el PO de OPAC y no
   garantiza que todos los PO requeridos estén disponibles.
4. `--update LANG` ejecuta en secuencia `remove_lang` y `install_lang`. No es
   atómico: puede dejar la traducción eliminada si la instalación falla. La
   rama observada de `update` no llama a `flush_cache`; `install` y `remove` sí
   limpian caché (global mediante `koha-foreach --enabled`, desarrollo mediante
   `koha-shell`). No se debe añadir una limpieza extra a `update`.
5. La comprobación `--dev` llama `is_instance` y `adjust_paths_git_install`.
   Este último solo cambia las rutas cuando la configuración XML de la
   instancia tiene `git_install` o el legado `dev_install` activo. Por ello,
   validar solo el patrón del nombre permite que una instancia de producción
   pase sintácticamente por `--dev`; el módulo debe leer su `koha-conf.xml` y
   exigir un indicador de instalación Git/desarrollo activo.
6. La cabecera del script impone `1 <= argc <= 4`. Con `--dev INSTANCE`, una
   operación e idioma consumen cuatro argumentos. Añadir `--verbose` consume
   cinco y no es compatible. Se rechaza `verbose: true` junto con
   `dev_instance`, antes de consultar o modificar.
7. Las plantillas Debian convencionales se comparten bajo el árbol de Koha;
   ejecutar sin `--dev` es global. `install` y `remove` limpian la caché de
   todas las instancias habilitadas. Instalar plantillas no activa las
   preferencias OPAC/Staff ni configura idiomas de usuarios.
8. El paquete `koha-l10n` provee los `.po` en instalaciones Debian actuales;
   `koha-core` lo declara dependencia/recomendación de paquete en el código
   actual. El módulo no instalará paquetes: informará la dependencia ausente.

La documentación de Ansible recomienda separar módulos de información del
módulo declarativo, priorizar `name`, ejecutar argv sin shell, admitir
`check_mode`, reportar fallos útiles y mantener una salida JSON estable. No se
incluye `translate_info`: la consulta se necesita para que el módulo principal
calcule el estado y no hay evidencia de una necesidad de inventario separada en
esta colección.

## Contrato y garantías

- `name` acepta alias `language` y `lang_code`; código restringido a segmentos
  ASCII alfanuméricos separados por guiones (por ejemplo `es-ES`).
- `state=present` y `state=absent` son idempotentes si no hay cambios externos.
  `update=true` fuerza la regeneración y puede informar `changed=true` en cada
  ejecución. `en` es el idioma base incluido por Koha: se informa instalado y
  no se puede eliminar ni actualizar.
- Antes de instalar se consulta disponibilidad exacta y `--check`; antes de
  actualizar se hace `--check`. Toda modificación se verifica con `--list`.
- Check mode solo consulta y planifica. Diff mode expone el estado semántico
  antes/después, sin comparar archivos `.po`.
- Las mutaciones usan `flock` bajo `/run/lock`, con un candado común para el
  árbol Debian compartido y otro por instancia git. El candado coordina solo
  ejecuciones de este módulo.
- `--dev` se limita a una instancia con `git_install`/`dev_install` activo y
  configuración Koha válida. No hay fallback al alcance global.
- Se excluye `--verbose --dev` por el límite de argumentos de 26.05.x/main.
  Las operaciones normales de desarrollo siguen soportadas.

## Matriz de compatibilidad conocida

| Koha | Evidencia | Estado |
| --- | --- | --- |
| 26.05.x | Script oficial de la rama consultado; el proyecto registra 26.05.04 en Ubuntu 24.04 | Diseño objetivo; integración real no disponible en este entorno |
| main (posterior a 26.05) | Script oficial consultado y sintaxis relevante coincidente | Compatibilidad esperada, no validada en host |
| Otras ramas/revisiones | No investigadas en este cambio | No declarar compatibles sin revisar el script empaquetado |

## Pruebas previstas y limitaciones del entorno

Se ejecutarán pruebas unitarias simuladas y las validaciones que estén
instaladas. Este checkout no tiene `koha-translate` ni `ansible` en PATH; las
pruebas de integración en Koha aislado quedan diseñadas/documentadas, no se
ejecutarán contra producción.
