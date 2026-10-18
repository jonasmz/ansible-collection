# `jmz.koha.plack`

Manage the Plack daemon and Plack enablement for one Koha instance. The module requires the Koha package that provides `koha-plack` on the managed host. Use `become: true` for lifecycle or enablement changes; Koha's service and Apache configuration are normally managed as root.

## Parameters

| Parameter | Type | Required | Values | Description |
| --- | --- | --- | --- | --- |
| `instance` | string | yes | Koha instance identifier | One instance per task. |
| `state` | string | no | `started`, `stopped`, `restarted`, `reloaded`, `status` | Daemon state. Omitted means observe only. |
| `enabled` | boolean | no | `true`, `false` | Enable or disable Plack in the instance's Apache configuration. |

At least one of `state` or `enabled` may be omitted. When both are omitted, the module queries state and makes no changes. `state: status` is read-only and cannot be combined with `enabled`.

`enabled` and `state` are independent. Koha's `koha-plack --enable` activates the Plack includes for both OPAC and staff interface and, with systemd, enables the unit for boot. It does not start the daemon. `--disable` reverses that configuration and systemd enablement; it does not stop a running daemon. Use `state: stopped` separately when required.

## Idempotence and check mode

The module reads the live Plack status and the active OPAC/intranet Apache includes before deciding whether to call `koha-plack`. `started` and `stopped` are idempotent. `restarted` and `reloaded` are explicit operations and report `changed: true` after success. Repeated enablement requests that already match configuration do not call `koha-plack`; this avoids the upstream utility's non-zero result when enablement is already in place.

Check mode performs read-only status and configuration queries, reports planned actions, and does not invoke mutating `koha-plack` operations. A requested restart or reload is reported as a planned change.

The module fails if the instance configuration is missing, the daemon status cannot be interpreted, or OPAC and intranet Plack includes disagree. It does not silently treat unknown status output as stopped.

## Examples

```yaml
- name: Start Plack
  jmz.koha.plack:
    instance: biblioteca
    state: started
  become: true

- name: Stop Plack
  jmz.koha.plack:
    instance: biblioteca
    state: stopped
  become: true

- name: Restart or gracefully reload Plack
  jmz.koha.plack:
    instance: biblioteca
    state: reloaded
  become: true

- name: Enable Plack without starting the daemon
  jmz.koha.plack:
    instance: biblioteca
    enabled: true
  become: true

- name: Enable Plack and start its daemon
  jmz.koha.plack:
    instance: biblioteca
    enabled: true
    state: started
  become: true

- name: Disable and stop Plack
  jmz.koha.plack:
    instance: biblioteca
    enabled: false
    state: stopped
  become: true

- name: Query state without changing the host
  jmz.koha.plack:
    instance: biblioteca
    state: status
  register: biblioteca_plack

- name: Start Plack for multiple instances
  jmz.koha.plack:
    instance: "{{ item }}"
    state: started
  loop:
    - biblioteca
    - archivo
  become: true
```

## Return values

The result includes `instance`, `running`, `enabled`, observed `state` (`running` or `stopped`), `actions`, and the status command's `rc`, `stdout`, and `stderr`. Unknown states result in a task failure rather than an invented value.

## Compatibility and limitations

- The collection requires `ansible-core >= 2.15`; the module uses only its standard module API and Python standard library.
- Koha must provide `koha-plack`, and the module currently follows packaged Koha instance naming (1 to 11 lowercase letters, digits, or hyphens, beginning with a letter).
- Koha's status command uses systemd status output or the SysV messages `Plack running for <instance>` / `Plack not running for <instance>`. Other or ambiguous output is rejected.
- The reported `enabled` value reflects Koha's Apache Plack includes. On systemd installations `koha-plack --enable/--disable` also updates the systemd unit's boot enablement.
