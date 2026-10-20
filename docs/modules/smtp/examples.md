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

## Depuración SMTP y timeout de la conexión

`debug` activa la depuración SMTP de Koha para ese servidor (por defecto `false`).
`smtp_timeout` es el tiempo máximo, en segundos, de la conexión SMTP; no es el
`timeout` de la tarea, que limita la llamada a `koha-shell`.

```yaml
- name: Configurar SMTP con depuración mientras se diagnostica
  jmz.koha.smtp:
    instance: biblioteca
    server:
      name: Notificaciones
      host: smtp.example.org
      port: 587
      ssl_mode: starttls
      user_name: notificaciones@example.org
      password: "{{ vault_smtp_password }}"
      debug: true
      smtp_timeout: 30
  become: true
  no_log: true
```

Para desactivarla, repita la tarea con `debug: false` (o sin `debug`): el servidor
se reconcilia con lo declarado.

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
