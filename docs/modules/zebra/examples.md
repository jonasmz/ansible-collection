# `jmz.koha.zebra`: escenarios de uso

[Guía del módulo](README.md) · [Índice de módulos](../README.md) ·
[Guía general](../../README.md) · [README de la colección](../../../README.md)

Usa `become: true` en los escenarios que modifican el servicio.

## Asegurar que Zebra está iniciado o detenido

Las solicitudes son idempotentes. Una segunda ejecución sin cambios observados
no vuelve a iniciar ni detener Zebra.

```yaml
- name: Asegurar Zebra iniciado
  jmz.koha.zebra:
    instance: biblioteca
    state: started
  become: true

- name: Asegurar Zebra detenido
  jmz.koha.zebra:
    instance: biblioteca
    state: stopped
  become: true
```

## Habilitar al arranque sin iniciar

`enabled` administra la habilitación persistente de la unidad Zebra systemd.
No cambia el estado de ejecución. En SysV esta operación no está soportada y
el módulo falla explícitamente.

```yaml
- name: Habilitar Zebra en el arranque
  jmz.koha.zebra:
    instance: biblioteca
    enabled: true
  become: true
```

## Reiniciar explícitamente

Un reinicio solicitado siempre ejecuta `koha-zebra --restart` y cuenta como un
cambio exitoso.

```yaml
- name: Reiniciar Zebra después de un mantenimiento
  jmz.koha.zebra:
    instance: biblioteca
    state: restarted
  become: true
```

## Solicitar ejecución y habilitación juntas

Se habilita antes de iniciar. Para detener y deshabilitar se detiene antes de
deshabilitar. Cada propiedad conserva su semántica independiente.

```yaml
- name: Habilitar y arrancar Zebra
  jmz.koha.zebra:
    instance: biblioteca
    enabled: true
    state: started
  become: true

- name: Detener y deshabilitar Zebra
  jmz.koha.zebra:
    instance: biblioteca
    state: stopped
    enabled: false
  become: true
```

## Consultar estado

`status` no cambia el servicio. Los resultados incluyen estado runtime,
backend, enablement y diagnósticos estructurados.

```yaml
- name: Consultar Zebra
  jmz.koha.zebra:
    instance: biblioteca
    state: status
  register: zebra_status

- name: Mostrar resultado
  ansible.builtin.debug:
    msg: >-
      {{ zebra_status.instance }}: state={{ zebra_status.state }},
      enabled={{ zebra_status.enabled }} ({{ zebra_status.enablement_state }}),
      backend={{ zebra_status.backend }}
```

## Administrar varias instancias

Se realiza una invocación independiente por instancia usando un loop.

```yaml
- name: Asegurar Zebra iniciado en las instancias seleccionadas
  jmz.koha.zebra:
    instance: "{{ item }}"
    state: started
  loop:
    - biblioteca
    - archivo
  become: true
```

## Check mode

El módulo consulta el estado y muestra las operaciones previstas. No ejecuta
`--start`, `--stop`, `--restart`, `--enable` ni `--disable`.

```yaml
- name: Previsualizar configuración de Zebra
  jmz.koha.zebra:
    instance: biblioteca
    enabled: true
    state: started
  become: true
  check_mode: true
```

## Prueba de integración en Debian o Ubuntu

Ejecute en una VM desechable con Koha instalado, un servicio systemd activo y
una instancia de prueba. No use una instalación sin systemd para validar la
unidad o `UnitFileState`.

1. Compruebe el estado inicial con `jmz.koha.zebra` en `state: status` y
   registre `state`, `enabled` y `enablement_state`.
2. Ejecute en check mode una solicitud que cambie el estado; confirme las
   acciones previstas y que no cambie el servicio.
3. Pruebe `state: stopped` y repítalo; la primera ejecución debe actuar si
   estaba iniciado y la segunda informar `changed: false`.
4. Pruebe `state: started` y repítalo con la misma expectativa de idempotencia.
5. Pruebe `enabled: true` y `enabled: false`, verificando la unidad exacta con
   `systemctl is-enabled koha-zebra@<instancia>.service`.
6. Pruebe `state: restarted` y confirme `changed: true`.
7. En una VM separada con paquete/version que use SysV, valide estado activo y
   detenido, y confirme que una solicitud `enabled` falla explícitamente.
8. En una VM separada, examine unidades `masked`, `static` o ausentes y
   confirme que el módulo devuelve el estado diferenciado sin atribuirle un
   booleano.

Esta estrategia comprueba el comportamiento integrado con systemd en un host
que realmente ejecuta systemd; los tests unitarios no sustituyen esa prueba.
