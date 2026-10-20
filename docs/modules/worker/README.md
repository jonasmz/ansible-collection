# `jmz.koha.worker`

Administra el ciclo de vida de los workers de background jobs de una instancia
Koha mediante el comando oficial `koha-worker`. Requiere Koha instalado desde
paquetes Debian o Ubuntu en el host administrado. Use `become: true` para las
operaciones que cambian procesos o configuración de inicio.

[Índice de módulos](../README.md) · [Guía general](../../README.md) ·
[Escenarios de uso](examples.md)

## Parámetros

| Parámetro | Tipo | Obligatorio | Valores | Descripción |
| --- | --- | --- | --- | --- |
| `instance` | string | sí | Identificador Koha | Instancia que se administrará. `name` sigue disponible como alias. |
| `state` | string | no | `started`, `stopped`, `restarted`, `status` | Estado operativo. Predeterminado: `status`. |
| `queue` | string | no | `default`, `long_tasks`, `all` | Cola que se administra. Predeterminado: `default`. `all` representa ambas colas y nunca se pasa como valor de `--queue`. |
| `enabled` | boolean | no | `true`, `false` | Habilita o deshabilita el inicio automático de forma independiente del estado operativo. Si se omite, conserva la configuración actual. |
| `quiet` | boolean | no | `true`, `false` | Pasa `--quiet` cuando la versión instalada lo anuncia. Predeterminado: `false`. No oculta los errores detectados por el módulo. |

## Estados e idempotencia

- `started` inicia únicamente los workers que no estén activos y verifica su
  estado final.
- `stopped` detiene únicamente los workers activos y verifica el resultado.
- `restarted` ejecuta siempre `koha-worker --restart`; reporta `changed: true`
  después de completar correctamente. Koha documenta que en SysV un worker
  detenido se inicia durante el reinicio.
- `status` es de solo lectura y devuelve `changed: false`. No puede combinarse
  con un valor explícito de `enabled`.

La ejecución y `enabled` son independientes. Por ejemplo, `enabled: true` no
inicia un proceso y `enabled: false` no lo detiene. Solicite ambas propiedades
en la misma tarea cuando corresponda.

## Colas y compatibilidad

Koha anuncia actualmente las colas `default` y `long_tasks`. Para `queue: all`,
el módulo emplea `--all-queues` si está disponible y si todas las colas requieren
la misma operación; en otro caso consulta y administra individualmente las
colas que necesitan cambios. La compatibilidad se basa en la ayuda del comando
instalado y en las unidades presentes, no en un número de versión supuesto.

En las instalaciones Koha con unidades systemd, el módulo consulta con
`systemctl show` las unidades por cola y ejecuta las acciones a través de
`koha-worker`. Los nombres esperados son `koha-worker@INSTANCIA.service` y
`koha-worker-long_tasks@INSTANCIA.service`. `enabled` se admite únicamente si
Koha anuncia `--enable` y `--disable` y las unidades informan un estado de
habilitación verificable.

En el backend SysV, el estado se obtiene del mensaje por cola de
`koha-worker --status`; el código de salida por sí solo no se considera prueba
de éxito o fallo. El módulo no ofrece `enabled` en ese backend porque Koha no
proporciona allí un mecanismo persistente verificable. Si el estado es ambiguo,
una unidad no existe o la instalación está incompleta, la tarea falla con un
diagnóstico en lugar de inferir que el worker está detenido.

La colección declara `ansible-core >= 2.15` y el módulo usa solo la API estándar
de Ansible y la biblioteca estándar de Python. El proyecto no fija una matriz
independiente de versiones de Python; use una versión admitida por `ansible-core`
instalado y disponible en el host administrado.

La fuente oficial [`koha-worker` de Koha](https://github.com/Koha-Community/Koha/blob/main/debian/scripts/koha-worker)
y [`koha-functions.sh`](https://github.com/Koha-Community/Koha/blob/main/debian/scripts/koha-functions.sh)
fueron consultadas el 2026-10-18. Confirman soporte de `--start`, `--stop`,
`--restart`, `--status`, `--queue`, `--all-queues`, `--quiet`, `--enable` y
`--disable` en la rama actual. La disponibilidad efectiva se comprueba en cada
host. Las unidades por-worker son propias del backend systemd actual; versiones
anteriores que utilicen el mecanismo `daemon` quedan en la ruta SysV.

En este checkout no están instalados Koha ni `koha-worker`, de modo que no se
pudo registrar ni ejecutar una versión concreta de paquete. Verifique la versión
y las unidades disponibles en el host objetivo antes de desplegar.

## Check mode y diff mode

Check mode consulta el estado y reporta operaciones pendientes sin ejecutar
acciones. Para `restarted`, informa el reinicio explícito previsto. Diff mode
muestra únicamente los valores `running` y `enabled` antes y después; no incluye
salidas del sistema ni información sensible.

## Resultado

`workers` es un diccionario por cola. Cada entrada informa `running`, `enabled`,
`changed` y `status`. `enabled` es `null` en SysV o si el estado de habilitación
no aplica. `status` distingue `running`, `stopped` y `failed`; las unidades
ausentes o los estados que no pueden interpretarse provocan un error.
`actions` enumera operaciones ejecutadas o
planificadas. Ante un fallo parcial, el módulo incluye las colas afectadas,
estados observados y diagnósticos en el resultado de error.

## Límites

El módulo solo administra ciclo de vida y habilitación de workers. No instala
Koha, modifica preferencias o trabajos, configura RabbitMQ, administra cron ni
interviene en Plack, Zebra o servicios de indexación.

## Pruebas

Las pruebas unitarias usan dobles de `koha-worker` y `systemctl`, por lo que no
requieren una instancia Koha ni cambian servicios reales. Ejecútelas con:

```console
python3 -m unittest tests.unit.test_worker -v
```

[Escenarios de uso](examples.md)
