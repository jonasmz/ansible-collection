# `jmz.koha.zebra_indexer`: escenarios de uso

[Guía del módulo](README.md) · [Índice de módulos](../README.md) ·
[Guía general](../../README.md) · [README de la colección](../../../README.md)

Use `become: true` en los escenarios que modifican el servicio.

## Arrancar o detener el indexador

```yaml
- name: Indexador en marcha
  jmz.koha.zebra_indexer:
    instance: biblioteca
    state: started
  become: true

- name: Indexador detenido
  jmz.koha.zebra_indexer:
    instance: biblioteca
    state: stopped
  become: true
```

## Arrancar solo si el motor es Zebra y su servidor está activo

```yaml
- name: Indexador con comprobaciones previas
  jmz.koha.zebra_indexer:
    instance: biblioteca
    state: started
    verify_zebra_engine: true
    require_zebra_running: true
  become: true
```

## Consultar y previsualizar

```yaml
- jmz.koha.zebra_indexer:
    instance: biblioteca
  register: indexer

- jmz.koha.zebra_indexer:
    instance: biblioteca
    state: restarted
  check_mode: true
  become: true
```

## Parar el indexador durante una reconstrucción completa

```yaml
- jmz.koha.zebra_indexer: {instance: biblioteca, state: stopped}
  become: true
- jmz.koha.zebra_rebuild: {instance: biblioteca, mode: full}
  become: true
- jmz.koha.zebra_indexer: {instance: biblioteca, state: started}
  become: true
```
