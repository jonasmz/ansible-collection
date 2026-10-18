# `jmz.koha.worker`: escenarios de uso

[Guía del módulo](README.md) · [Índice de módulos](../README.md) ·
[Guía general](../../README.md)

Use `become: true` para cambiar el estado operativo o la habilitación de workers.

## Iniciar una cola

```yaml
- name: Iniciar el worker general
  jmz.koha.worker:
    name: biblioteca
    state: started
    queue: default
  become: true
```

Para tareas de larga duración, use `queue: long_tasks`. Ambos estados son
idempotentes; si el worker ya coincide con lo solicitado, Koha no recibe una
operación de inicio o detención.

## Asegurar ambas colas y su inicio automático

```yaml
- name: Mantener workers activos y habilitados
  jmz.koha.worker:
    name: biblioteca
    state: started
    queue: all
    enabled: true
  become: true
```

La habilitación persistente no arranca procesos por sí sola. El ejemplo pide
explícitamente ambas propiedades.

## Reiniciar workers

```yaml
- name: Reiniciar todas las colas
  jmz.koha.worker:
    name: biblioteca
    state: restarted
    queue: all
  become: true
```

El reinicio es una operación explícita y reporta `changed: true` cuando
finaliza correctamente.

## Consultar estado

```yaml
- name: Consultar ambas colas
  jmz.koha.worker:
    name: biblioteca
    state: status
    queue: all
  register: worker_status

- name: Mostrar estado de cada cola
  ansible.builtin.debug:
    var: worker_status.workers
```

La consulta no modifica servicios. No combine `state: status` con `enabled`.

## Detener y deshabilitar

```yaml
- name: Detener workers y deshabilitar el inicio automático
  jmz.koha.worker:
    name: biblioteca
    state: stopped
    queue: all
    enabled: false
  become: true
```

## Administrar varias instancias

```yaml
- name: Asegurar workers de las bibliotecas
  jmz.koha.worker:
    name: "{{ item }}"
    state: started
    queue: all
  loop:
    - biblioteca_central
    - biblioteca_norte
    - biblioteca_sur
  become: true
```

Cada iteración consulta y administra exclusivamente la instancia indicada.

## Check mode

```yaml
- name: Revisar cambios previstos
  jmz.koha.worker:
    name: biblioteca
    state: started
    queue: all
    enabled: true
  become: true
  check_mode: true
```

El módulo devuelve `changed: true` si hay acciones pendientes, pero no inicia,
detiene, reinicia ni habilita unidades.
