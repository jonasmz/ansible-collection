# Ejemplos de `jmz.koha.localization`

## Instancia en español

~~~yaml
- name: Configurar Koha en español
  jmz.koha.localization:
    instance: biblioteca
    staff_languages:
      - es-ES
    opac_languages:
      - es-ES
    opac_language_selector: false
  become: true
~~~

## Instancia multilingüe

~~~yaml
- name: Configurar español como primera opción e inglés como alternativa
  jmz.koha.localization:
    instance: biblioteca
    staff_languages: [es-ES, en]
    opac_languages: [es-ES, en]
    opac_language_selector: true
    opac_selector_position: footer
    staff_selector_position: top
  become: true
~~~

## Idiomas independientes para cada interfaz

~~~yaml
- name: Mantener Staff en inglés y OPAC en español
  jmz.koha.localization:
    instance: biblioteca
    staff_languages: [en]
    opac_languages: [es-ES]
  become: true
~~~

## Cambio parcial

~~~yaml
- name: Permitir que lectores elijan el idioma del OPAC
  jmz.koha.localization:
    instance: biblioteca
    opac_language_selector: true
  become: true
~~~

Esta tarea preserva ambas listas de idiomas y las dos posiciones de selector.

## Previsualizar y mostrar diff

~~~yaml
- name: Previsualizar preferencias de idioma
  jmz.koha.localization:
    instance: biblioteca
    opac_languages: [es-ES, en]
    opac_selector_position: both
  check_mode: true
  diff: true
  become: true
~~~

## Prueba de integración aislada

En una VM o contenedor Debian/Ubuntu descartable con `koha-l10n`, Koha
inicializado y una instancia de prueba:

1. Instale `es-ES` con `jmz.koha.translate` si aún no está disponible.
2. Ejecute configuración de español en ambas interfaces; compruebe las
   preferencias desde el helper o la interfaz de administración.
3. Repita la tarea y confirme `changed: false`.
4. Añada `en` y cambie el orden; confirme que invertir la lista reporta cambio.
5. Ejecute un cambio parcial de selector y confirme que las listas permanecen.
6. Ejecute `--check --diff`; confirme que el plan es visible y la base no cambia.
7. Repita en dos instancias distintas y consulte ambas para verificar aislamiento.

Estos son pasos propuestos, no resultados ejecutados en este workspace.
