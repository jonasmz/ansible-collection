# `jmz.koha.worker`: escenarios de uso

[Guía del módulo](README.md) · [Índice de módulos](../README.md) ·
[Guía general](../../README.md) · [README de la colección](../../../README.md)

Use `become: true` en los escenarios que modifican procesos.

## Ambas colas en marcha

```yaml
- name: Workers en marcha
  jmz.koha.worker:
    instance: biblioteca
    queue: all
    state: started
  become: true
```

## Una sola cola

```yaml
- name: Reiniciar el worker general
  jmz.koha.worker:
    instance: biblioteca
    state: restarted
  become: true

- name: Detener la cola de tareas largas
  jmz.koha.worker:
    instance: biblioteca
    queue: long_tasks
    state: stopped
  become: true
```

## Consultar

```yaml
- name: Estado de los workers
  jmz.koha.worker:
    instance: biblioteca
    queue: all
  register: workers
- ansible.builtin.debug:
    msg: "{{ workers.workers }}"
```

## Previsualizar

```yaml
- jmz.koha.worker:
    instance: biblioteca
    queue: all
    state: stopped
  check_mode: true
  become: true
```
