# `jmz.koha.zebra_rebuild`: escenarios de uso

[Guía del módulo](README.md) · [Índice de módulos](../README.md) ·
[Guía general](../../README.md) · [README de la colección](../../../README.md)

Use `become: true`: la utilidad exige privilegios de root.

## Reconstrucción completa inicial

```yaml
- name: Zebra en marcha
  jmz.koha.zebra: {instance: biblioteca, state: started}
  become: true

- name: Reconstrucción completa
  jmz.koha.zebra_rebuild:
    instance: biblioteca
    mode: full
    require_zebra_running: true
  become: true
  async: 7200
  poll: 30
```

## Reconstrucción completa silenciosa

```yaml
- jmz.koha.zebra_rebuild:
    instance: biblioteca
    mode: full
    quiet: true
    verbose: 0
  become: true
```

La tarea termina en `ok` aunque la utilidad no imprima nada.

## Actualización incremental

```yaml
- name: Solo los registros bibliográficos pendientes
  jmz.koha.zebra_rebuild:
    instance: biblioteca
    target: biblios
  become: true
  register: rebuild

- ansible.builtin.debug:
    msg: "{{ rebuild.skip_reason }}"
  when: rebuild.work_skipped
```

Con el indexador activo (`USE_INDEXER_DAEMON=yes`) no se ejecuta nada, `work_skipped` es verdadero y
la tarea **no falla** ni aparece como `SKIPPED`. Para forzarlo:

```yaml
- jmz.koha.zebra_rebuild:
    instance: biblioteca
    target: authorities
    force: true
  become: true
```

## Parar el indexador mientras se reconstruye

```yaml
- jmz.koha.zebra_indexer: {instance: biblioteca, state: stopped}
  become: true
- jmz.koha.zebra_rebuild: {instance: biblioteca, mode: full}
  become: true
- jmz.koha.zebra_indexer: {instance: biblioteca, state: started}
  become: true
```

## Previsualizar

```yaml
- jmz.koha.zebra_rebuild:
    instance: biblioteca
    mode: full
  check_mode: true
  become: true
```

Valida todo lo de solo lectura y devuelve el comando previsto en `command`, con `executed: false`.

## Varias instancias

```yaml
- jmz.koha.zebra_rebuild:
    instance: "{{ item }}"
    mode: full
  loop: [biblioteca, archivo]
  become: true
```
