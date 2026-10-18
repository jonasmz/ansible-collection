# Ejemplos de `jmz.koha.initialize`

[Guía del módulo](README.md) · [Índice de módulos](../README.md) ·
[Guía general](../../README.md)

Las tareas `present` requieren las entidades declaradas y reglas explícitas de
circulación. Ajuste los códigos y las reglas a la política de su biblioteca. La
contraseña debe provenir de Ansible Vault y las tareas que la contienen deben
usar `no_log: true`.

## Inicialización con onboarding

```yaml
- name: Inicializar la instancia biblioteca
  jmz.koha.initialize:
    instance: biblioteca
    state: present
    language: es-ES
    marc_flavour: MARC21
    library:
      code: CENTRAL
      name: Biblioteca Central
    patron_categories:
      - code: STAFF
        description: Personal bibliotecario
        type: S
        enrolment_period: 1
        default_privacy: default
      - code: ADULT
        description: Usuarios adultos
        type: A
        enrolment_period: 1
        default_privacy: default
    administrator:
      username: admin
      firstname: Administrador
      surname: Koha
      cardnumber: ADMIN001
      library: CENTRAL
      category: STAFF
      password: "{{ vault_koha_admin_password }}"
    item_types:
      - code: BOOK
        description: Libros
    circulation_rules:
      - library: CENTRAL
        category: ADULT
        item_type: BOOK
        rules:
          issuelength: 14
          lengthunit: days
          maxissueqty: 5
          renewalsallowed: 2
  become: true
  no_log: true
```

Los valores de circulación del ejemplo son ilustrativos. Confirme los nombres
de regla válidos y sus ámbitos para la versión instalada de Koha.

## Seleccionar UNIMARC y datos de ejemplo

```yaml
- name: Inicializar usando UNIMARC e importar un conjunto opcional aprobado
  jmz.koha.initialize:
    instance: biblioteca
    language: es-ES
    marc_flavour: UNIMARC
    sample_data:
      - "optional/sample_biblios.sql"
    # library, patron_categories, administrator, item_types y circulation_rules
    # se declaran igual que en el ejemplo anterior.
  become: true
  no_log: true
```

El identificador debe existir en el catálogo instalado de Koha. Los datos
obligatorios y los frameworks MARC obligatorios se cargan independientemente
del parámetro `sample_data`.

## Inspección sin cambios

```yaml
- name: Consultar el estado de inicialización
  jmz.koha.initialize:
    instance: biblioteca
    state: inspect
  register: koha_initialization
  become: true

- name: Mostrar estado detectado
  ansible.builtin.debug:
    msg: "{{ koha_initialization.current_state }}"
```

## Check mode

```yaml
- name: Previsualizar la inicialización
  jmz.koha.initialize:
    instance: biblioteca
    language: es-ES
    marc_flavour: MARC21
    library:
      code: CENTRAL
      name: Biblioteca Central
    # Declare aquí las categorías, el administrador, los tipos y reglas.
  become: true
  check_mode: true
  no_log: true
```

El plan es parcial: no se escribe en la base, y los conflictos de atributos o
reglas se verifican durante una ejecución normal.

## Idempotencia y manejo de fallos parciales

Repita la tarea para verificar las entidades declaradas. Si los atributos
gestionados coinciden, no se crean objetos ni se cambia la contraseña. Si un
objeto existente difiere, la tarea falla para evitar una reconciliación
silenciosa.

Una importación SQL interrumpida se clasifica `data_incomplete` y bloquea el
reintento automático porque las APIs de instalación repiten archivos
obligatorios. Determine el estado de la base y aplique el procedimiento de
recuperación correspondiente antes de volver a ejecutar.
