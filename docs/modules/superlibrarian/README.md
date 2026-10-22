# `jmz.koha.superlibrarian`

Restablece la cuenta superlibrarian de una instancia Koha a su estado
declarado y avisa de cualquier otro superlibrarian. Es un control de
cumplimiento para correr en cada playbook (o de forma periódica), pensado para
instalaciones donde otros usuarios tienen `staffaccess` y podrían alterar esa
cuenta.

[Índice de módulos](../README.md) · [Guía general](../../README.md) ·
[Ejemplos](examples.md)

## Por qué existe

Un usuario con `staffaccess` puede, en Koha, cambiar la contraseña, el
vencimiento o los datos de un superlibrarian, y borrarlo;
`ProtectSuperlibrarianPrivileges` solo protege el privilegio. `jmz.koha.initialize`
no lo corrige: acepta la cuenta, rellena un correo vacío y falla si cambió la
identidad. Este módulo cubre ese hueco, y `jmz.koha.user` sigue sin poder
tocar a un superlibrarian.

## Requisitos

- Debian/Ubuntu con Koha empaquetado y `koha-shell`.
- Ejecutar con `become: true` y después de `jmz.koha.initialize`; la biblioteca
  y la categoría (de personal, tipo `S`) deben existir.
- `files/superlibrarian.pl` es un helper Perl empaquetado en la colección. El
  action plugin lo copia temporalmente a `/tmp`, lo ejecuta en `koha-shell` con
  la petición JSON por stdin y elimina el directorio.

## Parámetros

| Parámetro | Tipo | Obligatorio | Semántica |
| --- | --- | --- | --- |
| `instance` | string | sí | Identificador 1–11 caracteres, minúsculas/números/guiones, comienza con letra. |
| `username` | string | sí | `userid` de la cuenta. |
| `password` | secreto | sí | Cumple la política de la categoría. Marcada `no_log`. |
| `surname` | string | sí | Apellido. |
| `library` | string | sí | Biblioteca existente. |
| `category` | string | sí | Categoría de personal (tipo `S`) existente. |
| `firstname`, `cardnumber`, `email` | string | no | Si se omiten, no se modifican. |
| `allowed` | lista | no | Otros `userid` que pueden ser superlibrarian sin aviso ni bloqueo. |
| `unexpected` | string | no | `warn` (predeterminado) solo informa de los demás superlibrarians; `lock` además los bloquea. |
| `timeout` | entero | no | Timeout de `koha-shell`, predeterminado 120 s. |

## Qué restablece

En cada ejecución compara con el estado real y corrige:

- **Privilegio:** si perdió `superlibrarian`, deja los flags solo con ese
  privilegio, como lo crea `initialize`.
- **Identidad:** nombre, apellido, tarjeta, correo, biblioteca y categoría.
- **Contraseña:** se compara con el hash y se restablece solo si difiere.
- **Vigencia:** si está vencida, calcula un nuevo vencimiento con el período de
  inscripción de la categoría.
- **Acceso:** quita el bloqueo administrativo y los bloqueos por intentos fallidos.
- **Restricciones:** elimina las restricciones de la cuenta.
- **Cuenta borrada:** la crea de nuevo.

## Otros superlibrarians

Cualquier otro usuario con el privilegio superlibrarian que no sea `username`
ni esté en `allowed` se devuelve en `unexpected_superlibrarians` y se informa
como advertencia (`warnings`). La advertencia no falla la tarea. Qué más ocurre
depende de `unexpected`:

- **`warn`** (predeterminado): nada más. No se modifica a nadie.
- **`lock`**: además bloquea esas cuentas con el bloqueo administrativo de Koha.
  El bloqueo impide iniciar sesión, pero **no** quita el privilegio, no vence la
  cuenta, no borra reservas ni toca nada más, y es reversible. Se devuelven en
  `locked_superlibrarians`. Quien las desbloquee a mano vuelve a quedar
  bloqueado en la siguiente ejecución.

Con `lock`, los superlibrarians declarados en `allowed` que estén bloqueados (por
ejemplo por una ejecución anterior en que aún no se habían declarado) se
desbloquean y se devuelven en `restored_superlibrarians`. **Es lo único que se
desbloquea**: un superlibrarian no declarado que alguien bloqueó a mano
permanece bloqueado, y ninguna cuenta sin el privilegio se promueve.

Antes de usar `lock`, declare en `allowed` las cuentas de servicio con
privilegio superlibrarian (integraciones, SIP, scripts); si no, se bloquearían.
Check mode informa a quién bloquearía sin hacerlo.

### Qué identifica una cuenta en `allowed`

El `userid` de Koha (`borrowers.userid`), no el número de tarjeta, el correo ni
el `borrowernumber`. La comparación es exacta y distingue mayúsculas: `Soporte`
no coincide con `soporte`, y con `lock` esa cuenta se bloquearía. Un `userid`
inexistente o de un usuario sin el privilegio se ignora; `allowed` nunca
promueve a nadie.

### Varias cuentas permitidas

Una sola llamada gestiona a fondo la cuenta de `username`; de las cuentas de
`allowed` solo se ocupa del bloqueo (no se avisan ni se bloquean, y con
`lock` se desbloquean si estaban bloqueadas). Para restablecer también la
contraseña, la vigencia, la identidad y el privilegio de cada una hace falta una
llamada por cuenta, con las demás en `allowed`; ver
[Ejemplos](examples.md#varias-cuentas-permitidas).

## Límites

- No deshace lo que se haya hecho con la cuenta mientras estuvo alterada
  (usuarios creados, preferencias del sistema, etc.). Por eso existe el aviso de
  otros superlibrarians.
- Bloquear no cierra necesariamente una sesión ya abierta; no se verificó.
- Solo actúa cuando corre: el tiempo de exposición es el intervalo entre
  ejecuciones.
- No impide el cambio; la prevención es no conceder `staffaccess`.

## Idempotencia, check mode y diff

Repetir con la cuenta en regla devuelve `changed: false`. Check mode no escribe
y reporta qué se corregiría (`superlibrarian_restored`, `password_changed`,
`expiry_renewed`, `unlocked`, `restrictions_removed`, `updated`, `created`).
El diff y el retorno nunca incluyen la contraseña: es un booleano o, si esta
ejecución la cambió, `modificada`. Los cambios van en una transacción bajo un
lock por instancia.

## Pruebas

`extensions/molecule/superlibrarian_recovery` sabotea la cuenta de varias
formas y comprueba el restablecimiento contra Koha real.
