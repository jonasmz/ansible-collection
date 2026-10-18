# Documentación de jmz.koha

Esta colección administra instancias Koha instaladas desde paquetes Debian o Ubuntu. Sus módulos llaman las utilidades Koha empaquetadas en el host administrado; no instalan Koha.

## Primeros pasos

Instale la colección en el controlador Ansible:

```console
ansible-galaxy collection install jmz.koha
```

Ejecute las tareas de administración contra el host Koha. Use escalación de privilegios para operaciones que cambien la configuración o los servicios:

```yaml
- name: Iniciar Plack para la instancia biblioteca
  jmz.koha.plack:
    instance: biblioteca
    state: started
  become: true
```

Guarde las credenciales de base de datos y servicios en Ansible Vault u otro gestor de secretos. Las tareas que incluyan secretos deben usar `no_log: true`.

## Módulos

Consulte el [índice de módulos](modules/README.md) para ver su interfaz, comportamiento, limitaciones y ejemplos.

| Módulo | Propósito | Documentación | Ejemplos por escenario |
| --- | --- | --- | --- |
| [`jmz.koha.instance`](modules/instance/README.md) | Crear, configurar, inspeccionar, reparar o eliminar una instancia Koha. | [Guía](modules/instance/README.md) | [Escenarios](modules/instance/examples.md) |
| [`jmz.koha.plack`](modules/plack/README.md) | Administrar el daemon Plack y su habilitación por separado. | [Guía](modules/plack/README.md) | [Escenarios](modules/plack/examples.md) |
| [`jmz.koha.worker`](modules/worker/README.md) | Administrar workers de background jobs y su habilitación. | [Guía](modules/worker/README.md) | [Escenarios](modules/worker/examples.md) |

## Compatibilidad

La colección declara `ansible-core >= 2.15`. Las opciones de los comandos Koha y parte del comportamiento de los servicios dependen de la versión instalada en el host administrado. Revise las notas de compatibilidad de cada módulo antes de usarlo con otra versión de Koha.
