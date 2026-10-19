# jmz.koha.translate

Ensure a Koha translation is installed or absent with the official koha-translate
command. The module checks current state, runs only the needed operation, and
verifies the installed-language list afterward.

## Parameters

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| name | string | required | Exact language code, such as es-ES. Aliases: language, lang_code. |
| state | string | present | present or absent. |
| update | bool | false | Explicitly regenerate when state is present. |
| dev_instance | string | — | A Koha development instance marked git_install or dev_install. |
| verbose | bool | false | Pass --verbose. Unsupported together with dev_instance because the Koha CLI has a four-argument limit. |

Use become: true. The module requires an executable koha-translate and the Koha
script helpers/resources. On Debian packages, koha-l10n normally provides
translation PO files. The module does not install dependencies.

## Scope

Without dev_instance, Koha writes to its shared Debian application tree. This
operation affects the shared templates used by Koha instances, and Koha's
install/remove commands clear the cache for enabled instances. Do not loop this
global operation over production instances.

dev_instance selects a Git/development install only. The module verifies the
Koha config exists and has an enabled git_install or legacy dev_install value.
A normal production instance is rejected. All observations and operations use
the same --dev scope, and a failure never falls back to the global tree.

Koha instance names accepted by the Debian helper use lowercase letters,
numbers, and hyphens, up to 11 characters; names like koha_dev with an
underscore are invalid. Use the actual valid development instance name, for
example koha-dev.

## State and idempotence

For state present, the module checks the exact installed list. If absent, it
checks local availability and runs Koha's --check before --install. If already
installed, it does nothing unless update: true is explicitly requested.

For state absent, an already absent language is unchanged; an installed
language is removed and its absence is verified.

The built-in language en is reported installed. Koha does not permit installing,
updating, or removing it.

An explicit update is destructive: Koha's script removes the old translation
then installs it again. The operation is not atomic; an install error after the
remove may leave the translation absent. The module prechecks PO files and
checks post-state, but does not implement a fake rollback. Since Koha provides
no source revision test, update: true can return changed on every run.

## Availability and PO checks

koha-translate --available lists local candidate codes based on OPAC PO files.
It does not prove the complete set of required files is present. Before install
or update the module calls --check, which verifies the MARC21, UNIMARC, OPAC
bootstrap, preference, and staff prog PO files. A successful --check does not
prove the generated templates are functional.

If a code is not listed locally, the official local interface cannot determine
whether it is unknown globally or a recognized language whose PO files are not
installed. The module reports it as unavailable in local resources and points
to koha-l10n or the development PO checkout.

## Check mode, diff mode, and cache

Check mode performs read-only help, list, availability, and PO queries. It
returns changed: true and planned_action for a required install/update/remove,
without invoking a modifying operation or creating a lock.

Diff mode reports semantic installed state before and after. It does not read or
display generated files. An update diff marks regeneration as planned/performed;
it does not invent translation versions.

In the Koha 26.05.x script, install and remove clear caches. Update calls the
internal remove/install functions but does not reach the top-level cache clear.
The module does not run extra cache operations.

Installing templates does not enable OPACLanguages or StaffInterfaceLanguages,
change system preferences or SQL data, configure users, or initialize an
instance.

## Results and errors

The module returns name, state, installed, available, scope, dev_instance,
action_executed, planned_action, cmd, rc, stdout, stderr, and msg. available is
null when no availability query was needed. cmd is a safe argv list, not a shell
string. Output is bounded.

It distinguishes invalid codes, unavailable local resources, incomplete PO
files, non-development instances, missing executable/helper errors, CLI errors,
and unverified post-state where the underlying diagnostic permits. A failure
after invoking a mutator reports changed: true. Update/remove failures can
include partial: true because the state may have changed.

Mutating calls use a bounded flock under /run/lock. Global scope shares one
lock; development checkouts have separate locks. This only coordinates calls
from this module, not external Koha commands.

## Compatibility

The implementation was checked against upstream Koha 26.05.x and current main
koha-translate scripts. The collection's recorded deployed version is Koha
26.05.04.000 on Ubuntu 24.04. The checkout had no installed Koha command, so
this is source-based compatibility, not an end-to-end claim. Releases other
than the examined 26.05.x/main interfaces need verification on their installed
package. The script accepts no more than four command-line arguments, which is
why verbose and dev_instance cannot be combined.

## Examples

See examples.md for complete playbook tasks and an isolated integration-test
plan. Destructive tests must use a disposable Koha lab and must never run
against production.

