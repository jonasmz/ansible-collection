# Ejemplos de `jmz.koha.translate`

[Guía](README.md) · [Índice](../README.md) · [Guía general](../../README.md)

Estas tareas usan el FQCN de la colección y requieren privilegios administrativos en
el host de Koha.

## Instalar el español

```yaml
- name: Instalar la traducción al español
  hosts: koha_servers
  become: true
  tasks:
    - name: Asegurar las plantillas en español
      jmz.koha.translate:
        name: es-ES
        state: present
```

## Asegurar que el francés esté ausente

```yaml
- name: Quitar la traducción al francés
  hosts: koha_servers
  become: true
  tasks:
    - name: Asegurar que las plantillas en francés estén ausentes
      jmz.koha.translate:
        name: fr-FR
        state: absent
```

## Actualización explícita

```yaml
- name: Regenerar las plantillas en español
  hosts: koha_servers
  become: true
  tasks:
    - name: Actualizar explícitamente las plantillas instaladas
      jmz.koha.translate:
        name: es-ES
        state: present
        update: true
```

Puede informar `changed` en cada ejecución: la actualización de Koha elimina la
traducción actual antes de reinstalarla.

## Limitar el tiempo de una instalación

```yaml
- name: Instalar con un límite de tiempo
  jmz.koha.translate:
    name: es-ES
    timeout: 120
  become: true
```

Si `koha-translate` excede el límite, se termina y el resultado informa
`changed: true` y `partial: true`.

## Instalar el idioma y activarlo

`translate` solo instala las plantillas. Para usarlas en la interfaz, habilítelas con
[`jmz.koha.localization`](../localization/README.md):

```yaml
- name: Instalar el español
  jmz.koha.translate:
    name: es-ES
  become: true

- name: Activarlo en el personal y el OPAC
  jmz.koha.localization:
    instance: biblioteca
    staff_languages: [es-ES, en]
    opac_languages: [es-ES, en]
  become: true
```

## Check mode y diff

```yaml
- name: Previsualizar los cambios de traducción
  jmz.koha.translate:
    name: es-ES
    state: present
  check_mode: true
  diff: true
  become: true
```

## Prueba de integración aislada

Las pruebas unitarias simulan el ejecutable de Koha. Para una comprobación real use
una VM o un contenedor Debian/Ubuntu desechable con Koha y `koha-l10n`; el escenario
de molecule `translate_localization` lo hace automáticamente. No ejecute esta
secuencia contra una instalación de producción.

1. Registre `koha-translate --list` y verifique que `es-ES` aparezca en
   `--list --available`.
2. Ejecute el módulo con `state: present`; debe informar `changed` y `es-ES` debe
   figurar como instalado.
3. Repita la tarea; `changed` debe ser `false`.
4. Ejecute con `update: true`; el comando debe terminar y `es-ES` seguir listado.
5. Ejecute con `state: absent`; debe informar `changed` y `es-ES` debe desaparecer.
6. Repita `state: absent`; `changed` debe ser `false`.
7. En una copia desechable del directorio de PO, quite un archivo requerido y
   verifique que la instalación falla antes de modificar nada.
8. Ejecute el check mode y verifique que no se invoca ningún modificador.
9. Observe aparte los efectos de caché: en Koha 26.05.x instalar y quitar limpian la
   caché; actualizar no llama a la función de limpieza de nivel superior.

Los pasos 1 a 6 y 8 los ejecuta el escenario de molecule contra Koha 26.05.04.
