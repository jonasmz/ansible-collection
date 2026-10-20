# Documentación de módulos

Esta sección reúne la referencia y las guías de uso de todos los módulos de `jmz.koha`.

Cada carpeta de módulo incluye una guía general y un archivo `examples.md` con
escenarios de uso explicados.

Las opciones con un conjunto declarado de valores aceptados ignoran
mayúsculas/minúsculas y espacios externos, y se convierten a la grafía canónica
del módulo antes de validarse. Los textos libres conservan su contenido.

| Módulo | Descripción | Referencia | Ejemplos |
| --- | --- | --- | --- |
| [`jmz.koha.instance`](instance/README.md) | Crear y administrar declarativamente una instancia Koha. | [Guía del módulo](instance/README.md) | [Escenarios](instance/examples.md) |
| [`jmz.koha.plack`](plack/README.md) | Administrar el daemon Plack y su habilitación para una instancia. | [Guía del módulo](plack/README.md) | [Escenarios](plack/examples.md) |
| [`jmz.koha.initialize`](initialize/README.md) | Inicializar datos de Koha y completar el onboarding inicial. | [Guía del módulo](initialize/README.md) | [Escenarios](initialize/examples.md) |
| [`jmz.koha.localization`](localization/README.md) | Configurar idiomas y selectores OPAC/Staff. | [Guía del módulo](localization/README.md) | [Escenarios](localization/examples.md) |
| [`jmz.koha.smtp`](smtp/README.md) | Agregar un servidor SMTP y establecerlo como predeterminado. | [Guía del módulo](smtp/README.md) | [Escenarios](smtp/examples.md) |
| [`jmz.koha.worker`](worker/README.md) | Administrar workers de background jobs y su habilitación. | [Guía del módulo](worker/README.md) | [Escenarios](worker/examples.md) |
| [`jmz.koha.zebra`](zebra/README.md) | Administrar el servicio Zebra de una instancia. | [Guía del módulo](zebra/README.md) | [Escenarios](zebra/examples.md) |
| [`jmz.koha.zebra_indexer`](zebra_indexer/README.md) | Administrar el daemon de indexación incremental Zebra de una instancia. | [Guía del módulo](zebra_indexer/README.md) | [Escenarios](zebra_indexer/examples.md) |
| [`jmz.koha.zebra_rebuild`](zebra_rebuild/README.md) | Ejecutar actualizaciones incrementales y reconstrucciones puntuales de los índices Zebra. | [Guía del módulo](zebra_rebuild/README.md) | [Escenarios](zebra_rebuild/examples.md) |
| [`jmz.koha.translate`](translate/README.md) | Administrar traducciones Koha mediante `koha-translate`. | [Guía del módulo](translate/README.md) | [Escenarios](translate/examples.md) |

[Volver a la guía general](../README.md) · [Volver al README de la colección](../../README.md)
