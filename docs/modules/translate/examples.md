# Playbook examples

These tasks use the collection FQCN and require administrative privileges for
the Koha host.

## Install Spanish globally

~~~yaml
- name: Install Spanish translation
  hosts: koha_servers
  become: true
  tasks:
    - name: Ensure Spanish templates are installed
      jmz.koha.translate:
        name: es-ES
        state: present
~~~

## Ensure French is absent

~~~yaml
- name: Remove French translation
  hosts: koha_servers
  become: true
  tasks:
    - name: Ensure French templates are absent
      jmz.koha.translate:
        name: fr-FR
        state: absent
~~~

## Explicit update

~~~yaml
- name: Regenerate Spanish templates
  hosts: koha_servers
  become: true
  tasks:
    - name: Explicitly update installed Spanish templates
      jmz.koha.translate:
        name: es-ES
        state: present
        update: true
~~~

This can report changed on every run. Koha's update removes the current
translation before reinstalling it.

## Development checkout

~~~yaml
- name: Install Spanish in the development checkout
  hosts: koha_dev_hosts
  become: true
  tasks:
    - name: Ensure development translation is installed
      jmz.koha.translate:
        name: es-ES
        state: present
        dev_instance: koha-dev
~~~

The name must be a real Koha instance configured with git_install or
dev_install enabled. A production instance name is rejected. Do not combine
verbose: true with dev_instance.

## Check and diff mode

~~~yaml
- name: Preview translation changes
  hosts: koha_servers
  become: true
  tasks:
    - name: Show the semantic plan
      jmz.koha.translate:
        name: es-ES
        state: present
      check_mode: true
      diff: true
~~~

## Isolated integration-test design

The unit tests simulate the Koha executable. For a real integration check,
prepare a disposable Debian/Ubuntu VM or container with Koha, koha-l10n, and a
development instance if testing --dev. Do not run this sequence against a
production installation.

1. Record the initial koha-translate --list and verify es-ES appears in
   --list --available.
2. Run the module with state present; verify it reports changed and es-ES is
   listed as installed.
3. Run the same task again; verify changed is false.
4. Run with update true; verify the command completes and es-ES remains listed.
5. Run with state absent; verify changed and es-ES disappears.
6. Run state absent again; verify changed is false.
7. In a disposable copy of the PO directory, remove one required file and
   verify installation fails before mutation.
8. Run check mode and verify no mutator is invoked.
9. If a dev checkout is configured, repeat list/check/install/remove with
   dev_instance and verify the global installed list is unaffected.
10. Observe cache effects separately: Koha 26.05.x install/remove clear cache;
    update does not call the top-level flush_cache function.

These are test procedures, not results from this workspace. No Koha installation
or koha-translate executable was available for integration execution.

