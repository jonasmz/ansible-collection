# `jmz.koha.zebra`: escenarios de uso

[Guía del módulo](README.md) · [Índice de módulos](../README.md) ·
[Guía general](../../README.md) · [README de la colección](../../../README.md)

Use `become: true` en los escenarios que modifican el servicio.

## Asegurar Zebra iniciado o detenido

```yaml
- name: Zebra en marcha
  jmz.koha.zebra:
    instance: biblioteca
    state: started
  become: true

- name: Zebra detenido
  jmz.koha.zebra:
    instance: biblioteca
    state: stopped
  become: true
```

Repetir la tarea no vuelve a actuar (`changed: false`).

## Reiniciar tras cambiar la configuración

```yaml
- name: Reiniciar Zebra
  jmz.koha.zebra:
    instance: biblioteca
    state: restarted
  become: true
```

## Consultar sin cambiar nada

```yaml
- name: Estado de Zebra
  jmz.koha.zebra:
    instance: biblioteca
  register: zebra
- ansible.builtin.debug:
    msg: "Zebra está {{ zebra.state }}"
```

## Previsualizar

```yaml
- name: Qué haría con Zebra
  jmz.koha.zebra:
    instance: biblioteca
    state: restarted
  check_mode: true
  become: true
```

`changed: true` y `planned: true`; `state` es el proyectado.

## Varias instancias

```yaml
- jmz.koha.zebra:
    instance: "{{ item }}"
    state: started
  loop: [biblioteca, archivo]
  become: true
```

## Antes de reconstruir índices

Arranque Zebra y luego reconstruya con `jmz.koha.zebra_rebuild` y `require_zebra_running: true`.
