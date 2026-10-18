# `jmz.koha.plack` usage examples

[Module guide](README.md) · [Module index](../README.md) ·
[General guide](../../README.md)

These examples are task snippets for playbooks targeting the Koha host. Use
`become: true` for changes to Koha services or Apache configuration.

## Enable Plack without starting its daemon

`enabled` controls whether Koha's OPAC and staff Apache configurations use
Plack. It does not start the Plack process.

```yaml
- name: Enable Plack for biblioteca
  jmz.koha.plack:
    instance: biblioteca
    enabled: true
  become: true
```

## Start or stop the daemon

These requests are idempotent: the module only calls `koha-plack` when the
observed daemon state differs from the requested state.

```yaml
- name: Ensure Plack is running
  jmz.koha.plack:
    instance: biblioteca
    state: started
  become: true

- name: Ensure Plack is stopped
  jmz.koha.plack:
    instance: biblioteca
    state: stopped
  become: true
```

Stopping the daemon does not disable the Apache Plack configuration. Request
`enabled: false` separately if both properties should change.

## Restart or gracefully reload

`restarted` restarts the daemon. `reloaded` asks Koha to reload it gracefully,
allowing active requests to finish. These are explicit operations, so a
successful invocation reports `changed: true` even if the daemon was already
running.

```yaml
- name: Gracefully reload Plack after deploying code
  jmz.koha.plack:
    instance: biblioteca
    state: reloaded
  become: true

- name: Restart Plack
  jmz.koha.plack:
    instance: biblioteca
    state: restarted
  become: true
```

## Enable and start together

The module applies the enablement change before the daemon lifecycle operation.
This keeps configuration and process state independent while allowing both to
be requested in one declarative task.

```yaml
- name: Enable and start Plack
  jmz.koha.plack:
    instance: biblioteca
    enabled: true
    state: started
  become: true
```

Likewise, disabling Plack does not stop an already running daemon. Ask for both
changes explicitly when desired:

```yaml
- name: Stop and disable Plack
  jmz.koha.plack:
    instance: biblioteca
    enabled: false
    state: stopped
  become: true
```

## Query state

With only `instance`, the module observes state without making changes. The
explicit `status` state is also read-only and cannot be combined with
`enabled`.

```yaml
- name: Query Plack state
  jmz.koha.plack:
    instance: biblioteca
    state: status
  register: biblioteca_plack

- name: Report Plack state
  ansible.builtin.debug:
    msg: >-
      {{ biblioteca_plack.instance }}: running={{ biblioteca_plack.running }},
      enabled={{ biblioteca_plack.enabled }}
```

## Manage multiple instances with a loop

Use one module invocation per instance so failures and results remain scoped to
the affected Koha site.

```yaml
- name: Ensure Plack is enabled and running for selected sites
  jmz.koha.plack:
    instance: "{{ item }}"
    enabled: true
    state: started
  loop:
    - biblioteca
    - archivo
  become: true
```

## Check mode

Check mode performs status and configuration reads, reports planned actions,
and does not execute start, stop, restart, reload, enable, or disable.

```yaml
- name: Preview Plack changes
  jmz.koha.plack:
    instance: biblioteca
    enabled: true
    state: started
  become: true
  check_mode: true
```
