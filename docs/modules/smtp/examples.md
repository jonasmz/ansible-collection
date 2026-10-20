# Ejemplos de `jmz.koha.smtp`

[Guía](README.md) · [Índice](../README.md) · [Guía general](../../README.md)

## STARTTLS con Vault

```yaml
- name: Configurar SMTP con STARTTLS como predeterminado
  jmz.koha.smtp:
    instance: biblioteca
    server:
      name: Notificaciones
      host: smtp.example.org
      port: 587
      ssl_mode: starttls
      user_name: notificaciones@example.org
      password: "{{ vault_smtp_password }}"
  become: true
  no_log: true
```

## SMTP con SSL

```yaml
- name: Configurar SMTP con SSL
  jmz.koha.smtp:
    instance: biblioteca
    server: {name: Notificaciones, host: smtp.example.org, port: 465, ssl_mode: ssl}
  become: true
```

## Después de initialize

```yaml
- name: Inicializar Koha
  jmz.koha.initialize:
    instance: biblioteca
    # ...
  become: true
  no_log: true

- name: Configurar SMTP
  jmz.koha.smtp:
    instance: biblioteca
    server: {name: Notificaciones, host: smtp.example.org}
  become: true
```

## Previsualizar cambios

```yaml
- name: Previsualizar SMTP
  jmz.koha.smtp:
    instance: biblioteca
    server: {name: Notificaciones, host: smtp.example.org, port: 587, ssl_mode: starttls}
  become: true
  check_mode: true
  diff: true
```
