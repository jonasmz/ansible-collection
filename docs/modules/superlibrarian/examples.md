# Ejemplos de `jmz.koha.superlibrarian`

## Mantener la cuenta administradora

```yaml
- name: Cuenta administradora en regla
  jmz.koha.superlibrarian:
    instance: biblioteca
    username: admin
    password: "{{ vault_admin_password }}"
    firstname: Ada
    surname: Koha
    cardnumber: ADMIN01
    email: admin@example.org
    library: CENTRAL
    category: STAFF
  become: true
  no_log: true
```

## Aceptar otro superlibrarian conocido

Todo superlibrarian que no sea `username` ni esté en `allowed` genera una
advertencia.

```yaml
- jmz.koha.superlibrarian:
    instance: biblioteca
    username: admin
    password: "{{ vault_admin_password }}"
    surname: Koha
    library: CENTRAL
    category: STAFF
    allowed: [soporte]
  become: true
  no_log: true
  register: admin
```

## Permitir solo a los declarados y bloquear el resto

`username` y los de `allowed` son los únicos superlibrarians activos; cualquier
otro se bloquea (sin quitarle el privilegio) y el bloqueo se mantiene en cada
ejecución. Declare aquí también las cuentas de servicio.

```yaml
- jmz.koha.superlibrarian:
    instance: biblioteca
    username: admin
    password: "{{ vault_admin_password }}"
    surname: Koha
    library: CENTRAL
    category: STAFF
    allowed: [soporte]
    unexpected: lock
  become: true
  no_log: true
  register: admin
```

Para readmitir a alguien bloqueado, añádalo a `allowed`: la siguiente ejecución
lo desbloquea. Un bloqueo manual de otra cuenta no declarada no se deshace.

## Varias cuentas permitidas

El campo que identifica cada cuenta en `allowed` es su `userid`. Con
`admin` como cuenta gestionada y `soporte` y `superuser3` como permitidas, una
sola llamada alcanza si solo se quiere que no se avisen ni se bloqueen (y que se
desbloqueen si estaban bloqueadas):

```yaml
- jmz.koha.superlibrarian:
    instance: biblioteca
    username: admin
    password: "{{ vault_admin_password }}"
    surname: Koha
    library: CENTRAL
    category: STAFF
    allowed: [soporte, superuser3]
    unexpected: lock
  become: true
  no_log: true
```

Para restablecer además la contraseña, la vigencia, la identidad y el
privilegio de **cada** cuenta, hace falta una llamada por cuenta. Cada una lleva
en `allowed` a todas las demás; si falta alguna, la llamada de otra cuenta la
bloquearía como inesperada. Definir la lista completa en una variable evita ese
error (este loop está verificado en el escenario `superlibrarian_recovery`):

```yaml
vars:
  superlibrarians:
    - {username: admin,      surname: Koha,    library: CENTRAL, category: STAFF, password: "{{ vault_admin_password }}"}
    - {username: soporte,    surname: Soporte, library: CENTRAL, category: STAFF, password: "{{ vault_soporte_password }}"}
    - {username: superuser3, surname: Tres,    library: CENTRAL, category: STAFF, password: "{{ vault_su3_password }}"}

tasks:
  - name: Superlibrarians en regla
    jmz.koha.superlibrarian:
      instance: biblioteca
      username: "{{ item.username }}"
      password: "{{ item.password }}"
      surname: "{{ item.surname }}"
      library: "{{ item.library }}"
      category: "{{ item.category }}"
      allowed: "{{ superlibrarians | map(attribute='username') | reject('equalto', item.username) | list }}"
      unexpected: lock
    loop: "{{ superlibrarians }}"
    loop_control:
      label: "{{ item.username }}"
    become: true
    no_log: true
```

## Fallar si aparece un superlibrarian inesperado

El módulo solo avisa; si quieres que el playbook falle, usa el retorno:

```yaml
- ansible.builtin.assert:
    that: admin.unexpected_superlibrarians | length == 0
    fail_msg: "Superlibrarians no previstos: {{ admin.unexpected_superlibrarians }}"
```

## Previsualizar

```yaml
- jmz.koha.superlibrarian: {instance: biblioteca, username: admin, password: "{{ pw }}", surname: Koha, library: CENTRAL, category: STAFF}
  become: true
  check_mode: true
  diff: true
  no_log: true
```
