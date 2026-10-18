# `jmz.koha.zebra_rebuild` examples

[Module guide](README.md) · [Module index](../README.md)

All examples run on the managed Koha host and require `become: true`.

## Initial full indexing

Start Zebra with its lifecycle module, then request a full rebuild explicitly.
Start the incremental indexer only after the initial rebuild completes:

```yaml
- name: Start Zebra for biblioteca
  jmz.koha.zebra:
    instance: biblioteca
    state: started
  become: true

- name: Build bibliographic and authority indexes
  jmz.koha.zebra_rebuild:
    instance: biblioteca
    mode: full
    target: all
    require_zebra_running: true
  become: true

- name: Start the incremental indexer
  jmz.koha.zebra_indexer:
    instance: biblioteca
    state: started
  become: true
```

## Separate index types

```yaml
- name: Update bibliographic indexes
  jmz.koha.zebra_rebuild:
    instance: biblioteca
    mode: incremental
    target: biblios
  become: true

- name: Rebuild authority indexes completely
  jmz.koha.zebra_rebuild:
    instance: biblioteca
    mode: full
    target: authorities
    verbose: 2
  become: true
```

## Daemon coordination

When the global Koha setting `USE_INDEXER_DAEMON` enables the permanent
indexer, Koha skips a normal incremental `koha-rebuild-zebra` request. The
module reports `status: skipped` and `changed: false`. If a one-off incremental
pass is required, coordinate it with the service owner, then explicitly set
`force: true`. Koha's own lock remains in force:

```yaml
- name: Run a coordinated one-off incremental pass
  jmz.koha.zebra_rebuild:
    instance: biblioteca
    target: all
    force: true
  become: true
```

The task does not stop `koha-indexer` or serialize separate playbook runs.
Use the lifecycle module and the playbook's orchestration to coordinate work.

## Long-running operations and check mode

```yaml
- name: Run a full rebuild with Ansible async polling
  jmz.koha.zebra_rebuild:
    instance: biblioteca
    mode: full
  async: 7200
  poll: 30
  become: true

- name: Review preflight and planned argv without rebuilding
  jmz.koha.zebra_rebuild:
    instance: biblioteca
    mode: full
    target: all
  check_mode: true
  become: true
```

An async task must be polled until its job completes before another rebuild is
submitted for that instance. Check mode still verifies the installation,
options, search engine, and requested service preconditions, but does not
inspect pending records.
