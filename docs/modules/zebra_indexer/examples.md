# `jmz.koha.zebra_indexer`: escenarios de uso

[Guía del módulo](README.md) · [Índice de módulos](../README.md) ·
[Guía general](../../README.md) · [README de la colección](../../../README.md)

Use `become: true` en tareas que cambian estado o habilitación.

## Asegurar inicio o detención

```yaml
- name: Mantener activo el indexador incremental
  jmz.koha.zebra_indexer:
    instance: biblioteca
    state: started
  become: true

- name: Detenerlo sin cambiar su habilitación
  jmz.koha.zebra_indexer:
    instance: biblioteca
    state: stopped
  become: true
```

Las solicitudes `started` y `stopped` son idempotentes. Una segunda ejecución
sin diferencias observadas no vuelve a invocar la acción.

## Habilitación persistente independiente

Solo backend systemd y versiones cuyo `koha-indexer --help` anuncie la opción
solicitada. No inicia ni detiene el daemon.

```yaml
- name: Habilitar el servicio para el próximo arranque
  jmz.koha.zebra_indexer:
    instance: biblioteca
    enabled: true
  become: true

- name: Deshabilitar sin detener el proceso actual
  jmz.koha.zebra_indexer:
    instance: biblioteca
    enabled: false
  become: true
```

En SysV, solicitar `enabled` falla explícitamente.

## Combinación de estado y enablement

Al iniciar, habilita antes del inicio. Al detener y deshabilitar, primero
detiene y luego deshabilita. Las dos propiedades siguen siendo independientes.

```yaml
- name: Habilitar e iniciar el indexador
  jmz.koha.zebra_indexer:
    instance: biblioteca
    enabled: true
    state: started
  become: true

- name: Detener y deshabilitarlo
  jmz.koha.zebra_indexer:
    instance: biblioteca
    state: stopped
    enabled: false
  become: true
```

## Reinicio solicitado explícitamente

Se ejecuta `koha-indexer --restart` aunque el estado previo sea detenido. La
postcondición que se verifica es que el indexador quede iniciado.

```yaml
- name: Reiniciar el indexador tras un cambio operativo externo
  jmz.koha.zebra_indexer:
    instance: biblioteca
    state: restarted
  become: true
```

## Validar motor y dependencia Zebra

Las validaciones son optativas. La preferencia se lee, no se modifica. Si Zebra
no está activo, la tarea falla sin iniciarlo; administre ese servicio con
`jmz.koha.zebra`.

```yaml
- name: Iniciar indexador solamente para motor Zebra con servidor activo
  jmz.koha.zebra_indexer:
    instance: biblioteca
    state: started
    verify_zebra_engine: true
    require_zebra_running: true
  become: true
```

`stopped` y `status` permanecen disponibles con esas validaciones habilitadas,
lo que permite diagnosticar y detener procesos residuales tras cambiar de motor.

## Estado, check mode y varias instancias

```yaml
- name: Consultar solo el estado
  jmz.koha.zebra_indexer:
    instance: biblioteca
    state: status
  register: indexer_status

- name: Previsualizar habilitación e inicio
  jmz.koha.zebra_indexer:
    instance: biblioteca
    enabled: true
    state: started
  check_mode: true
  become: true

- name: Asegurar indexador activo en dos instancias
  jmz.koha.zebra_indexer:
    instance: "{{ item }}"
    state: started
  loop: [biblioteca, archivo]
  become: true
```

En check mode no se invoca ninguna operación mutante. `state` y `enabled`
devuelven el estado observado y `planned_actions` muestra el plan.

## Validación de integración en Debian o Ubuntu

Use una VM desechable, una instancia Koha de prueba y una ventana de
mantenimiento. Las pruebas solo alteran el daemon; no deben usar catálogos
productivos ni provocar reconstrucciones de índice.

1. Registre estado mediante `state: status` y compare con `systemctl show
   koha-indexer@<instancia>.service` (systemd) o `koha-indexer --status
   <instancia>` (SysV).
2. Haga check mode con inicio, detención, reinicio y enablement, y confirme que
   el proceso y la habilitación no cambian.
3. Pruebe inicio y detención dos veces para confirmar idempotencia; pruebe
   reinicio desde activo y detenido y confirme que termina activo.
4. En systemd, pruebe `enabled: true/false` y estados no booleanos como `masked`
   o `static`; compruebe la unidad exacta.
5. En un paquete SysV separado, confirme que estado y ciclo de vida funcionan y
   que `enabled` falla explícitamente.
6. Pruebe las validaciones de motor con `SearchEngine: Zebra` y
   `SearchEngine: Elasticsearch`; pruebe Zebra detenido con
   `require_zebra_running: true` y confirme que no se inicia automáticamente.
7. Si `/etc/default/koha-common` define `ALTERNATE_INDEXER_DAEMON`, no ejecute
   pruebas de inicio/reinicio hasta validar manualmente el ejecutable alterno.

Estas comprobaciones de host real no se ejecutaron en el entorno de desarrollo:
no hay Koha instalado. La suite unitaria usa comandos simulados.
