# jmz.koha

Colección Ansible para automatizar instancias de Koha ILS instaladas desde paquetes Debian o Ubuntu.

La colección incluye módulos para crear y administrar instancias Koha, controlar sus servicios Plack, worker y Zebra, e inicializar la aplicación y su onboarding. Requiere `ansible-core >= 2.15` y que los comandos Koha estén instalados en el host administrado.

## Documentación

- [Guía general](docs/README.md): instalación, requisitos y navegación de la documentación.
- [Índice de módulos](docs/modules/README.md): descripción, interfaz y enlaces a la documentación general y ejemplos Markdown de cada módulo.
- [Guía de `jmz.koha.initialize`](docs/modules/initialize/README.md): inicialización de la base Koha y onboarding sin el instalador web.
- [Escenarios de `jmz.koha.initialize`](docs/modules/initialize/examples.md): playbooks para inicialización y configuración inicial.
- [Guía de `jmz.koha.translate`](docs/modules/translate/README.md): administración declarativa de traducciones Koha.
- [Escenarios de `jmz.koha.translate`](docs/modules/translate/examples.md): instalación, eliminación, actualización explícita y modo de comprobación.
- [Guía de `jmz.koha.zebra`](docs/modules/zebra/README.md): ciclo de vida Zebra, enablement por backend y resultados.
- [Escenarios de `jmz.koha.zebra`](docs/modules/zebra/examples.md): playbooks por escenario y estrategia de integración.
- [Guía de `jmz.koha.zebra_indexer`](docs/modules/zebra_indexer/README.md): ciclo de vida del indexador incremental y compatibilidad por backend.
- [Escenarios de `jmz.koha.zebra_indexer`](docs/modules/zebra_indexer/examples.md): playbooks, verificaciones opcionales y estrategia de integración.
- [Guía de `jmz.koha.zebra_rebuild`](docs/modules/zebra_rebuild/README.md): actualizaciones incrementales y reconstrucciones puntuales de Zebra.
- [Escenarios de `jmz.koha.zebra_rebuild`](docs/modules/zebra_rebuild/examples.md): coordinación con servicios Koha, check mode e integración.
- [Guía de `jmz.koha.worker`](docs/modules/worker/README.md): administración de workers de background jobs y su habilitación.
- [Escenarios de `jmz.koha.worker`](docs/modules/worker/examples.md): configuración y administración de workers por escenario.
- [Prueba de integración completa](docs/integration-test.md): playbook de referencia para provisionar y validar los módulos juntos.

Instale la colección con `ansible-galaxy collection install jmz.koha`.
