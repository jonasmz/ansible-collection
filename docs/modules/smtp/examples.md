# Ejemplos de `jmz.koha.smtp`

[Guía](README.md) · [Índice](../README.md) · [Guía general](../../README.md)

## STARTTLS con Vault

```yaml
- name: Configurar SMTP con STARTTLS
  jmz.koha.smtp:
    instance: biblioteca
    server:
      host: smtp.example.org
      port: 587
      timeout: 120
      ssl_mode: starttls
      user_name: notificaciones@example.org
      password: "{{ vault_smtp_password }}"
      debug: false
  become: true
  no_log: true
```

## SMTP con SSL

```yaml
- name: Configurar SMTP con SSL
  jmz.koha.smtp:
    instance: biblioteca
    server: {host: smtp.example.org, port: 465, ssl_mode: ssl}
  become: true
```

## Solo dirección administrativa

```yaml
- name: Configurar KohaAdminEmailAddress
  jmz.koha.smtp:
    instance: biblioteca
    admin_email_address: admin@example.org
  become: true
```

## Habilitar o deshabilitar sin cambiar transporte

```yaml
- name: Habilitar correo
  jmz.koha.smtp: {instance: biblioteca, enabled: true}
  become: true

- name: Deshabilitar correo
  jmz.koha.smtp: {instance: biblioteca, enabled: false}
  become: true
```

## Actualizar solo host y puerto

```yaml
- name: Conservar TLS y credenciales
  jmz.koha.smtp:
    instance: biblioteca
    server: {host: smtp.example.org, port: 587}
  become: true
```

## `initialize` antes de `smtp`

```yaml
- name: Inicializar Koha y configurar correo
  hosts: koha
  become: true
  tasks:
    - name: Inicializar instancia existente
      jmz.koha.initialize:
        instance: biblioteca
        language: es-ES
        marc_flavour: MARC21
        library: {code: CENTRAL, name: Biblioteca Central}
        patron_categories:
          - {code: STAFF, description: Personal, type: S, enrolment_period: 1, default_privacy: default}
          - {code: ADULT, description: Adultos, type: A, enrolment_period: 1, default_privacy: default}
        administrator:
          username: admin
          firstname: Administrador
          surname: Koha
          cardnumber: ADMIN001
          library: CENTRAL
          category: STAFF
          password: "{{ vault_koha_admin_password }}"
        item_types: [{code: BOOK, description: Libros}]
        circulation_rules:
          - library: CENTRAL
            category: ADULT
            item_type: BOOK
            rules: {issuelength: 14, lengthunit: days, maxissueqty: 5, renewalsallowed: 2}
      no_log: true

    - name: Configurar SMTP y correo Koha
      jmz.koha.smtp:
        instance: biblioteca
        server:
          host: smtp.example.org
          port: 587
          ssl_mode: starttls
          user_name: notificaciones@example.org
          password: "{{ vault_smtp_password }}"
        admin_email_address: admin@example.org
        enabled: true
      no_log: true
```

## Check mode y ejecución idempotente

```yaml
- name: Previsualizar los cambios
  jmz.koha.smtp:
    instance: biblioteca
    server: {host: smtp.example.org, port: 587, ssl_mode: starttls}
    enabled: true
  check_mode: true
  diff: true
  become: true

- name: Repetir configuración ya aplicada (changed false)
  jmz.koha.smtp:
    instance: biblioteca
    server: {host: smtp.example.org, port: 587, ssl_mode: starttls}
    enabled: true
  become: true
```

El diff no incluye la contraseña. Si existe un SMTP default en la base, una
solicitud `server` falla con el detalle de precedencia; la configuración DB
requiere otro backend explícito.
