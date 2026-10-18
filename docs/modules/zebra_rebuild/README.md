# `jmz.koha.zebra_rebuild`

Run an imperative incremental update or a requested full rebuild of the Zebra
indexes for exactly one Koha instance. The module uses the packaged
`koha-rebuild-zebra` command and does not manage `koha-zebra` or
`koha-indexer` services.

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `instance` | string | yes | — | One existing Koha instance. Use an Ansible loop for multiple instances. |
| `mode` | string | no | `incremental` | `incremental` or explicit `full`. |
| `target` | string | no | `all` | `all`, `biblios`, or `authorities`. For `all`, the utility is called separately for both index types so partial failures can be reported. |
| `force` | bool | no | `false` | Pass `--force` for incremental indexing when the global indexer daemon setting would otherwise cause Koha to skip the work. Rejected with `mode: full`. |
| `verbose` | integer | no | `1` | Number of `--verbose` flags, from 0 to 3. |
| `quiet` | bool | no | `false` | Pass `--quiet`. Set `verbose: 0` when enabling quiet. |
| `verify_search_engine` | bool | no | `true` | Read `SearchEngine` via `koha-shell` and require `Zebra`; inconclusive reads fail. |
| `require_zebra_running` | bool | no | `false` | Require the instance's Zebra service to be running. Never starts it. |
| `command_path` | path | no | `/usr/sbin/koha-rebuild-zebra` | Absolute executable path to the official Koha wrapper. |

## Execution behavior

The command's options are checked against its installed `--help` output before
the operation. Commands are passed as argv lists; arbitrary Perl arguments are
not accepted. The task requires root privileges because the Koha wrapper
switches to the instance's `-koha` account itself. Use `become: true`.

Incremental indexing is skipped by the Koha wrapper unless
`USE_INDEXER_DAEMON=no`, `--force` is supplied, or a full rebuild is requested.
The module inspects only simple static assignments in
`/etc/default/koha-common`, never sources shell code. If the value cannot be
determined safely, it refuses to claim that incremental work ran. `force` does
not disable Koha's own lock or bypass other preflight checks. Coordinate
maintenance with the indexer daemon and let Koha's lock serialize work.

For `target: all`, bibliographic and authority passes are separate invocations.
This makes an observable partial result possible and avoids interpreting the
wrapper's overall exit code as proof that both passes succeeded. Recognized
failure, skip, and lock diagnostics cause a failed task. Output formats vary
between Koha releases; unrecognized output is `unknown` and fails closed. A
`completed` result means the selected pass returned successfully and had no
recognized failure diagnostic. It does **not** establish search correctness,
index integrity, or a record count. `records_processed` is therefore null.

This operation is intentionally not idempotent. Every successful invocation
reports `changed: true`, including an incremental pass with no pending records.
Check mode runs read-only preflight checks and returns the planned command with
`changed: true`; it does not report that records are pending or guarantee a
future index modification. Ansible `async` and `poll` can supervise long full
rebuilds without the module creating background jobs.

Full rebuilds can require substantial free disk space, memory, CPU, and I/O.
They may reduce search availability while the index is regenerated. Request a
full rebuild explicitly and schedule it for a maintenance window. The module
does not delete index directories, restart services, remove lock files, retry
work, or automatically recover an incremental failure.

## Integration order

For a new installation, a typical playbook starts `jmz.koha.zebra`, runs an
initial `mode: full` rebuild, then starts `jmz.koha.zebra_indexer`. The rebuild
module itself does not enforce this orchestration. For maintenance, coordinate
the indexer lifecycle in the playbook; do not launch a second rebuild while a
previous Ansible async job remains active.

## Examples and integration testing

See [examples.md](examples.md). A destructive integration test must use an
isolated Debian/Ubuntu Koha lab instance and disposable known bibliographic and
authority records. Do not run the integration procedure against production or
modify real records without a verified backup and recovery procedure.

The integration plan compares expected search results using Koha's normal
staff/OPAC search or an approved read-only search interface before and after
the rebuild. Run independent bibliographic and authority queries. To test an
incremental update, make a lab-only record change, execute one incremental
pass, and verify that the changed record becomes searchable. For lock handling,
hold the official Koha rebuild lock with a controlled lab process and confirm
the task reports `blocked`; never remove the lock as part of the test. For
inconsistent-index recovery, corrupt only disposable lab indexes after taking
a snapshot, run an explicit full rebuild, and verify the saved expected search
results. Restore the disposable lab snapshot between destructive cases.

## Compatibility

The command interface is validated at runtime through the installed help text,
but Koha package releases can differ in warning text and internal behavior.
This module was designed against the Koha Community [`main` implementation of
`debian/scripts/koha-rebuild-zebra`](https://github.com/Koha-Community/Koha/blob/main/debian/scripts/koha-rebuild-zebra)
(reviewed 2026-10-18); no installed Koha
release was available in this workspace for end-to-end validation. Confirm
the package's `--help`, lock diagnostics, preference utility location, and
`USE_INDEXER_DAEMON` behavior on each supported Debian/Ubuntu Koha release.
