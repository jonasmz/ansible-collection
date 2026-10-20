# `jmz.koha.plack`: escenarios de uso

[Guía del módulo](README.md) · [Índice de módulos](../README.md) ·
[Guía general](../../README.md) · [README de la colección](../../../README.md)

Use `become: true` en los escenarios que modifican el demonio o Apache. Los módulos de Apache
`headers` y `proxy_http` deben estar habilitados.

## Activar, arrancar y recargar Apache

```yaml
- name: Plack activo y en marcha
  jmz.koha.plack:
    instance: biblioteca
    enabled: true
    state: started
    reload_apache: true
  become: true
```

## Activar y recargar Apache con un handler

```yaml
- name: Plack activo y en marcha
  jmz.koha.plack:
    instance: biblioteca
    enabled: true
    state: started
  become: true
  register: plack
  notify: Reload Apache

handlers:
  - name: Reload Apache
    ansible.builtin.service: {name: apache2, state: reloaded}
    become: true
```

`plack.apache_reload_required` indica si hubo cambios en Apache.

## Solo activar, sin arrancar

```yaml
- jmz.koha.plack:
    instance: biblioteca
    enabled: true
    reload_apache: true
  become: true
```

## Parar, reiniciar y recargar el demonio

```yaml
- jmz.koha.plack: {instance: biblioteca, state: stopped}
  become: true
- jmz.koha.plack: {instance: biblioteca, state: restarted}
  become: true
- jmz.koha.plack: {instance: biblioteca, state: reloaded}
  become: true
```

## Volver a CGI

```yaml
- jmz.koha.plack:
    instance: biblioteca
    state: stopped
    enabled: false
    reload_apache: true
  become: true
```

## Consultar y previsualizar

```yaml
- jmz.koha.plack:
    instance: biblioteca
  register: plack

- jmz.koha.plack:
    instance: biblioteca
    enabled: false
  check_mode: true
  become: true
```

## Varias instancias

```yaml
- jmz.koha.plack:
    instance: "{{ item }}"
    enabled: true
    state: started
    reload_apache: true
  loop: [biblioteca, archivo]
  become: true
```
