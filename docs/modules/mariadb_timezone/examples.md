# Ejemplos de `jmz.koha.mariadb_timezone`

[Guía](README.md) · [Índice](../README.md) · [Guía general](../../README.md)

## Antes de crear una instancia

```yaml
- name: Cargar las zonas horarias de MariaDB
  jmz.koha.mariadb_timezone:
    timezone: America/Argentina/Buenos_Aires
  become: true

- name: Crear la instancia con esa zona
  jmz.koha.instance:
    instance: biblioteca
    timezone: America/Argentina/Buenos_Aires
  become: true
```

## Reiniciar solo si hace falta

```yaml
- name: Cargar las tablas y reiniciar MariaDB únicamente si la carga no basta
  jmz.koha.mariadb_timezone:
    timezone: America/Argentina/Buenos_Aires
    restart: true
  become: true
```

El reinicio corta las conexiones de todas las bases del servidor; en MariaDB 10.11
la carga por sí sola suele bastar.

## Previsualizar

```yaml
- name: Ver si hace falta cargar las tablas
  jmz.koha.mariadb_timezone:
    timezone: America/Argentina/Buenos_Aires
  become: true
  check_mode: true
```
