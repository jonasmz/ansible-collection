# Ejemplos de `jmz.koha.user`

## Personal de circulación y catálogo

```yaml
- name: Bibliotecaria operativa
  jmz.koha.user:
    instance: biblioteca
    username: mperez
    password: "{{ vault_mperez_password }}"
    firstname: María
    surname: Pérez
    library: CENTRAL
    category: STAFF
    email: mperez@example.org
    permissions:
      catalogue: true
      circulate: [circulate_remaining_permissions, force_checkout]
      reserveforothers: true
  become: true
  no_log: true
```

## Moderador: operación completa y gestión de usuarios, sin configuración técnica

Todo el trabajo diario (catálogo, usuarios, préstamos, reservas, multas,
adquisiciones, series, listas, clubes…), la gestión de otros usuarios y sus
permisos (`permissions` y `staffaccess`) y solo la administración funcional de
`parameters` (bibliotecas, categorías, tipos de ítem, reglas de circulación…).
Queda fuera lo técnico: `superlibrarian`, `manage_sysprefs`, SMTP, motor de
búsqueda, proveedores de identidad, trabajos en segundo plano, plugins, SIP2,
logs del sistema y reportes SQL propios. Está verificado en el escenario
`user_permissions`.

**Riesgo asumido:** con `permissions` y `staffaccess` el usuario puede asignar
permisos a cualquier miembro del personal, incluido él mismo. Con
`ProtectSuperlibrarianPrivileges` activada (el valor predeterminado de Koha) no
puede conceder `superlibrarian`, pero sí darse `parameters: manage_sysprefs` y
desactivar esa preferencia. Por eso el perfil excluye lo técnico solo mientras
se confíe en quien lo recibe, y el módulo, al ser declarativo, devuelve la
cuenta a este perfil en cada ejecución.

```yaml
vars:
  moderator_permissions:
    catalogue: true
    circulate: true
    borrowers: true
    reserveforothers: true
    permissions: true
    staffaccess: true
    editcatalogue: true
    updatecharges: true
    acquisition: true
    suggestions: true
    editauthorities: true
    serials: true
    coursereserves: true
    lists: true
    clubs: true
    ill: true
    stockrotation: true
    cash_management: true
    problem_reports: true
    recalls: true
    erm: true
    loggedinlibrary: true
    preservation: true
    reports: [execute_reports]
    parameters:
      - manage_libraries
      - manage_patron_categories
      - manage_itemtypes
      - manage_circ_rules
      - manage_auth_values
      - manage_cities
      - manage_patron_attributes
      - manage_accounts
      - manage_transfers
      - manage_item_circ_alerts
      - manage_marc_frameworks
      - manage_classifications
      - manage_matching_rules
      - manage_patron_restrictions
      - manage_cash_registers
      - manage_curbside_pickups
    tools:
      - edit_calendar
      - edit_notices
      - edit_notice_status_triggers
      - label_creator
      - inventory
      - stage_marc_import
      - manage_staged_marc
      - export_catalog
      - import_patrons
      - edit_patrons
      - items_batchmod
      - items_batchdel
      - records_batchmod
      - records_batchdel
      - manage_patron_lists
      - manage_csv_profiles
      - batch_extend_due_dates
      - batch_modify_holds
      - batch_upload_patron_images
      - delete_anonymize_patrons
      - rotating_collections
      - moderate_comments
      - moderate_tags
      - upload_local_cover_images

tasks:
  - name: Moderador
    jmz.koha.user:
      instance: biblioteca
      username: moderador
      password: "{{ vault_moderador_password }}"
      surname: Moderador
      library: CENTRAL
      category: STAFF
      permissions: "{{ moderator_permissions }}"
    become: true
    no_log: true
```

## Módulo completo

`circulate: true` concede todo el módulo de circulación.

## Revocar permisos

Quitar un módulo de `permissions` lo revoca en la siguiente ejecución.

## Previsualizar

```yaml
- jmz.koha.user: {instance: biblioteca, username: mperez, password: "{{ pw }}", surname: Pérez, library: CENTRAL, category: STAFF, permissions: {catalogue: true}}
  become: true
  check_mode: true
  diff: true
  no_log: true
```
