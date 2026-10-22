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
| [`jmz.koha.plack`](modules/plack/README.md) | Administrar el daemon Plack y su activación en Apache. | [Guía](modules/plack/README.md) | [Escenarios](modules/plack/examples.md) |
| [`jmz.koha.initialize`](modules/initialize/README.md) | Inicializar la base Koha y el onboarding sin el instalador web. | [Guía](modules/initialize/README.md) | [Escenarios](modules/initialize/examples.md) |
| [`jmz.koha.mariadb_timezone`](modules/mariadb_timezone/README.md) | Cargar las tablas de zonas horarias de un MariaDB local. | [Guía](modules/mariadb_timezone/README.md) | [Escenarios](modules/mariadb_timezone/examples.md) |
| [`jmz.koha.smtp`](modules/smtp/README.md) | Agregar un servidor SMTP y establecerlo como predeterminado. | [Guía](modules/smtp/README.md) | [Escenarios](modules/smtp/examples.md) |
| [`jmz.koha.user`](modules/user/README.md) | Crear un usuario y establecer sus permisos operativos. | [Guía](modules/user/README.md) | [Escenarios](modules/user/examples.md) |
| [`jmz.koha.worker`](modules/worker/README.md) | Administrar workers de background jobs. | [Guía](modules/worker/README.md) | [Escenarios](modules/worker/examples.md) |
| [`jmz.koha.zebra`](modules/zebra/README.md) | Administrar el servicio Zebra de una instancia. | [Guía](modules/zebra/README.md) | [Escenarios](modules/zebra/examples.md) |
| [`jmz.koha.zebra_indexer`](modules/zebra_indexer/README.md) | Administrar el daemon de indexación incremental Zebra de una instancia. | [Guía](modules/zebra_indexer/README.md) | [Escenarios](modules/zebra_indexer/examples.md) |
| [`jmz.koha.zebra_rebuild`](modules/zebra_rebuild/README.md) | Ejecutar actualizaciones incrementales y reconstrucciones puntuales de índices Zebra. | [Guía](modules/zebra_rebuild/README.md) | [Escenarios](modules/zebra_rebuild/examples.md) |

## Despliegues de ejemplo

- [Una instancia Koha lista para uso](single-instance-deployment.md): playbook,
  ejecución y resultados en la VM de integración.
- [Prueba de integración de todos los módulos](integration-test.md): escenario
  integral de QA.

## Compatibilidad

La colección declara `ansible-core >= 2.15`. Las opciones de los comandos Koha y parte del comportamiento de los servicios dependen de la versión instalada en el host administrado. Revise las notas de compatibilidad de cada módulo antes de usarlo con otra versión de Koha.
